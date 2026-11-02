// v69: the login allowlist (admin only). Its own exports, matching the root layout's: a
// prerendered shell (`users.html`, nginx's `location = /users`) that reads the list in the browser.
export const ssr = false;
export const prerender = true;
