"use client";

/**
 * A tiny client-side cache for the /api routes, shared across page navigations.
 *
 * Why this exists: every tab fetches its whole table on mount, and the Airtable
 * round-trip is most of the wait. Opening the site used to mean staring at an
 * empty tab for that whole round-trip, because the fetch could not start until
 * the tab's JS had loaded, which could not start until you clicked. The landing
 * page now starts these fetches while the reader is still reading the hero
 * (see `warm` below), so by the time they click a tab the data is already in
 * flight or already here.
 *
 * Because Next's App Router keeps the JS context alive across client-side
 * navigation, a module-level Map survives the move from / to /states. A hard
 * load straight to /states just misses the cache and fetches normally.
 *
 * Deliberately not a store, a context, or a library: pages keep their own
 * useState and their own shape, and the only change at each call site is the
 * function name.
 */

const TTL_MS = 5 * 60 * 1000;

/** url -> { at, promise } */
const cache = new Map();

/**
 * Fetch a JSON endpoint, reusing an in-flight or recent response.
 *
 * Failures are never cached — neither a rejected fetch nor a body carrying an
 * `error` key — so a reader who arrives during an Airtable blip gets a real
 * retry on their next navigation instead of a stuck error for the whole TTL.
 */
export function loadJSON(url) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.at < TTL_MS) return hit.promise;

  const promise = fetch(url)
    .then((r) => r.json())
    .then((d) => {
      if (d && d.error) cache.delete(url);
      return d;
    });
  promise.catch(() => cache.delete(url));

  cache.set(url, { at: Date.now(), promise });
  return promise;
}

/**
 * Start loading endpoints nobody has asked for yet.
 *
 * The returned promise settles when they all have, which is what the landing
 * page's counters wait on. Rejections are swallowed here: warming is an
 * optimisation, and a warm failure must never surface as an error on a page
 * that is not showing that data.
 */
export function warm(urls) {
  return Promise.all(urls.map((u) => loadJSON(u).catch(() => null)));
}
