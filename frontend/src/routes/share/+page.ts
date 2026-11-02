// v65: the installed app's share target (manifest `share_target`, GET /share?title&text&url).
// Its own exports, as the plan asks, matching the root layout's: a prerendered shell
// (`share.html`, nginx's `location = /share`) that reads the share in the browser.
export const ssr = false;
export const prerender = true;
