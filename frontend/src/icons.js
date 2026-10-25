export const paths = {
  home: '<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  wallet:
    '<rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 8h18m-5 5h5m-4 3h.01"/>',
  people:
    '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5a3 3 0 0 1 0 6m2 4a5 5 0 0 1 3 5"/>',
  card: '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M2 10h20M6 15h4"/>',
  document: '<path d="M5 3h9l5 5v13H5zM14 3v6h5M9 13h6m-6 4h6"/>',
  chart: '<path d="M4 3v17h17M8 15v-4m5 4V7m5 8V4"/>',
  spark:
    '<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z"/>',
  bell: '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5zm5 3h4"/>',
  chat: '<path d="M21 11a9 9 0 0 1-9 9H4l-2 2V11a9 9 0 0 1 19 0Z"/><path d="M7 10h9m-9 4h6"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  refresh:
    '<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 5M4 13a8 8 0 0 0 14 5"/>',
  sliders:
    '<path d="M4 7h16M4 17h16"/><rect x="8" y="4" width="4" height="6" rx="1"/><rect x="14" y="14" width="4" height="6" rx="1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  like: '<path d="M8 21H3V10h5m0 11h9a2 2 0 0 0 2-1.5L21 12a2 2 0 0 0-2-2h-5l1-5a2 2 0 0 0-3-2l-4 7z"/>',
  dislike:
    '<g transform="rotate(180 12 12)"><path d="M8 21H3V10h5m0 11h9a2 2 0 0 0 2-1.5L21 12a2 2 0 0 0-2-2h-5l1-5a2 2 0 0 0-3-2l-4 7z"/></g>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
};
export const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.document}</svg>`;
