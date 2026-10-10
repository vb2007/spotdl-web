-- v38 task 5: tracks downloaded again after their first copy had been moved into the library.
-- Read-only. Run as: psql "$DATABASE_URL" -f scripts/moved_file_redownloads.sql
--
-- Two signatures, one row per (spotify id, signature):
--
--   ledger_back_in_downloads  The ledger row is flagged in_library (the sort moved it once)
--                             but its file_path points outside the library root again. That is
--                             exactly what a re-download leaves: download_track's db.merge()
--                             repoints file_path to the new /downloads copy and never touches
--                             in_library. The library copy is still on disk (the sweep never
--                             deletes there), so the track now has two files.
--
--   repeat_network_download   More than one completed attempt that recorded a network path for
--                             the same Spotify id. Broader: it also counts re-downloads of a
--                             file deleted by hand, and (before v35's fix) spotdl's own
--                             "file already exists" skip, which recorded `completed
--                             direct-ipv4` without touching the network. network_path exists
--                             since v29, so older re-downloads aren't visible here.
with library as (
    -- No app_settings row yet means the code default (AppSettings.library_target_dir).
    select coalesce((select library_target_dir from app_settings limit 1),
                    '/mnt/raid1/media/music') as root
),
back_in_downloads as (
    select d.spotify_track_id,
           'ledger_back_in_downloads' as signature,
           d.file_path as detail
    from downloaded_tracks d, library l
    where d.in_library
      and d.file_path not like l.root || '/%'
),
repeat_network as (
    select t.spotify_track_id,
           'repeat_network_download' as signature,
           count(*) || ' network downloads, '
               || to_char(min(a.finished_at), 'YYYY-MM-DD HH24:MI') || ' .. '
               || to_char(max(a.finished_at), 'YYYY-MM-DD HH24:MI') as detail
    from track_attempts a
    join tracks t on t.id = a.track_id
    where a.outcome = 'completed'
      and a.network_path is not null
    group by t.spotify_track_id
    having count(*) > 1
)
select spotify_track_id, signature, detail from back_in_downloads
union all
select spotify_track_id, signature, detail from repeat_network
order by signature, spotify_track_id;
