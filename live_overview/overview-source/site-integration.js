/* Miniconf integration: conference info comes from sitedata config.yml (frozen into
   public-site-config.js at build time); backend state is never altered, only how it is shown. */
(function () {
  'use strict';
  const conf = window.ISMIR_PUBLIC_CONFIG?.conference || {};
  // The backend still emits links to this host; the frontend retargets them to the configured miniconf.
  const BACKEND_PROGRAM_SITE = 'https://ismir2026program.ismir.net';
  const programSite = String(conf.miniconfUrl || BACKEND_PROGRAM_SITE).replace(/\/+$/, '');

  function programUrl(href) {
    const value = String(href || '');
    if (programSite === BACKEND_PROGRAM_SITE || !value.startsWith(BACKEND_PROGRAM_SITE + '/')) return value;
    return programSite + value.slice(BACKEND_PROGRAM_SITE.length);
  }

  function zoomRedirectUrl(href) {
    let url;
    try { url = new URL(programUrl(href)); } catch (_) { return null; }
    const base = new URL(programSite + '/zoom.html');
    return url.origin === base.origin && url.pathname === base.pathname && url.searchParams.get('event_uid') ? url : null;
  }

  function localizeLinks(links) {
    if (!links || typeof links !== 'object') return;
    for (const key of Object.keys(links)) if (typeof links[key] === 'string') links[key] = programUrl(links[key]);
    // Only the miniconf redirect page may be shown; never a raw Zoom URL.
    if (links.zoom && !zoomRedirectUrl(links.zoom)) delete links.zoom;
  }

  function localizeState(state) {
    for (const event of state?.events || []) {
      for (const item of [event, ...(event.papers || [])]) {
        localizeLinks(item.links);
        if (item.detailUrl) item.detailUrl = programUrl(item.detailUrl);
      }
    }
    return state;
  }

  function applyConferenceText(root = document) {
    const values = { name: conf.name, date: conf.date };
    root.querySelectorAll('[data-conf]').forEach((node) => {
      const value = values[node.dataset.conf];
      if (value) node.textContent = value;
    });
    if (conf.name) document.title = document.title.replace(/ISMIR \d{4}/g, conf.name);
  }

  window.ISMIRSite = {
    conference: conf,
    programSite,
    timeZone: conf.timezone || 'Asia/Dubai',
    programUrl,
    zoomRedirectUrl,
    localizeState,
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => applyConferenceText());
  else applyConferenceText();
})();
