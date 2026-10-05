/* Publication content stays in the Jekyll templates; saved IDs stay in this browser. */
(() => {
  'use strict';
  const section = document.querySelector('#publications');
  if (!section) return;
  const normalize = text => text.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  const clean = text => text.replace(/\s+/g, ' ').trim();
  const topics = [...section.querySelectorAll('[data-publication-filter]')];
  const views = [...section.querySelectorAll('[data-publication-view]')];
  const input = section.querySelector('#publication-search');
  const year = section.querySelector('#publication-year');
  const earlier = section.querySelector('.earlier-publications');
  const collection = section.querySelector('.publication-collection');
  const savedFilter = section.querySelector('[data-saved-filter]');
  const exploreButton = section.querySelector('[data-explore-paper]');
  const dialog = document.querySelector('.paper-dialog');
  const canOpenDialog = dialog && typeof dialog.showModal === 'function';
  const storageKey = 'srijit-seal-reading-list-v1';
  const records = [...section.querySelectorAll('[data-publication]')].map(element => {
    const title = clean(element.querySelector('.publication-title').textContent);
    const venue = clean(element.querySelector('.publication-venue-label').textContent);
    const authors = [...element.querySelectorAll('.author-block')].map(author => clean(author.textContent).replace(/,$/, ''));
    const links = [...element.querySelectorAll('.publication-links a')];
    const preferred = ['Paper', 'Journal', 'arXiv', 'bioRxiv', 'PDF', 'Project'].map(label => links.find(link => clean(link.textContent) === label)).find(Boolean);
    const id = element.dataset.publicationId;
    return { element, id, title, venue, authors, links, isOlder: earlier.contains(element), url: preferred ? preferred.href : '',
      year: (venue.match(/\b(?:19|20)\d{2}\b/) || [''])[0], image: element.querySelector('.publication-image img'),
      tags: element.dataset.tags.split(/\s+/), search: normalize([title, venue, ...authors, id].join(' ')) };
  });
  const byId = new Map(records.map(record => [record.id, record]));
  const years = [...new Set(records.map(record => record.year).filter(Boolean))].sort().reverse();
  years.forEach(value => year.add(new Option(value, value)));
  let state;
  let saved = readSaved();
  let current = null;
  let opener = null;
  const explored = new Set();
  let lastExplored = null;
  let swipeStart = null;

  function readSaved() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || '[]');
      return new Set(Array.isArray(value) ? value.filter(id => byId.has(id)) : []);
    } catch { return new Set(); }
  }

  function readState() {
    const params = new URL(location.href).searchParams;
    state = {
      topic: topics.some(button => button.dataset.publicationFilter === params.get('topic')) ? params.get('topic') : 'all',
      year: years.includes(params.get('year')) ? params.get('year') : 'all',
      view: params.get('view') === 'list' ? 'list' : 'figures',
      saved: params.get('saved') === '1', q: (params.get('q') || '').slice(0, 300)
    };
    input.value = state.q;
    year.value = state.year;
  }

  function syncURL() {
    const url = new URL(location.href);
    const values = { topic: state.topic === 'all' ? '' : state.topic, year: state.year === 'all' ? '' : state.year, view: state.view === 'figures' ? '' : state.view, saved: state.saved ? '1' : '', q: state.q.trim() };
    Object.entries(values).forEach(([key, value]) => value ? url.searchParams.set(key, value) : url.searchParams.delete(key));
    history.replaceState(null, '', url);
  }

  function announce(message) {
    const target = canOpenDialog && dialog.open ? dialog.querySelector('[data-paper-status]') : section.querySelector('[data-action-status]');
    target.textContent = message;
  }

  function updateSaveButtons() {
    records.forEach(record => {
      const button = record.element.querySelector('[data-save-publication]');
      const active = saved.has(record.id);
      button.setAttribute('aria-pressed', String(active));
      button.title = active ? 'Remove from reading list' : 'Save publication';
      button.setAttribute('aria-label', (active ? 'Remove from reading list: ' : 'Save ') + record.title);
      button.querySelector('i').className = (active ? 'fas' : 'far') + ' fa-bookmark';
    });
    section.querySelector('[data-saved-count]').textContent = String(saved.size);
    section.querySelector('[data-download-saved]').disabled = !saved.size;
    if (canOpenDialog && current) {
      const button = dialog.querySelector('[data-paper-save]');
      const active = saved.has(current.id);
      button.setAttribute('aria-pressed', String(active));
      button.querySelector('i').className = (active ? 'fas' : 'far') + ' fa-bookmark';
      button.querySelector('span').textContent = active ? 'Saved' : 'Save';
    }
  }

  function toggleSaved(record) {
    if (saved.has(record.id)) saved.delete(record.id); else saved.add(record.id);
    let persisted = true;
    try { localStorage.setItem(storageKey, JSON.stringify([...saved])); } catch { persisted = false; }
    apply();
    announce(persisted ? (saved.has(record.id) ? 'Publication saved.' : 'Publication removed from the reading list.') : 'The change applies to this visit only.');
    if (current && dialog.open) updateNavigation();
  }

  function viewRecords() {
    return state.view === 'figures' ? records.filter(record => record.image).concat(records.filter(record => !record.image)) : records;
  }

  function apply(resetArchive = false) {
    const figures = state.view === 'figures';
    // Move the same records between views so there is one bookmark and one title per paper.
    if (figures !== collection.classList.contains('is-figure-view')) {
      viewRecords().forEach(record => {
        if (figures) collection.append(record.element);
        else if (record.isOlder) earlier.append(record.element);
        else collection.insertBefore(record.element, earlier);
      });
    }
    const terms = normalize(state.q).split(' ').filter(Boolean);
    const matchesWithoutYear = record => (state.topic === 'all' || record.tags.includes(state.topic)) && (!state.saved || saved.has(record.id)) && terms.every(term => record.search.includes(term));
    const matching = records.filter(matchesWithoutYear);
    let count = 0;
    let olderCount = 0;
    records.forEach(record => {
      const show = matchesWithoutYear(record) && (state.year === 'all' || record.year === state.year);
      record.element.hidden = !show;
      if (show) { count++; if (record.isOlder) olderCount++; }
    });
    [...year.options].forEach(option => {
      const countForYear = option.value === 'all' ? matching.length : matching.filter(record => record.year === option.value).length;
      option.textContent = (option.value === 'all' ? 'All years' : option.value) + ' (' + countForYear + ')';
    });
    const filtered = state.topic !== 'all' || state.year !== 'all' || state.q.trim() !== '' || state.saved;
    const expanded = filtered || state.view === 'figures';
    earlier.hidden = figures || olderCount === 0;
    if (expanded) earlier.open = true; else if (resetArchive) earlier.open = false;
    earlier.querySelector('summary').hidden = expanded;
    collection.classList.toggle('is-figure-view', state.view === 'figures');
    topics.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicationFilter === state.topic)));
    views.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.publicationView === state.view)));
    savedFilter.setAttribute('aria-pressed', String(state.saved));
    const empty = section.querySelector('[data-publication-empty]');
    empty.hidden = count !== 0;
    empty.textContent = state.saved && saved.size === 0 ? 'Your reading list is empty.' : 'No publications match your filters.';
    section.querySelector('[data-publication-count]').textContent = count + (count === 1 ? ' publication' : ' publications');
    exploreButton.disabled = count === 0;
    section.querySelector('[data-reset-publications]').hidden = !filtered;
    updateSaveButtons();
  }

  function changed() { apply(true); syncURL(); }

  function citation(record) {
    return record.authors.join('; ') + '.\n' + record.title + (/[.?!]$/.test(record.title) ? '' : '.') + '\n' + record.venue + '.\n' + record.url;
  }

  function download(text, filename) {
    const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  }

  async function copy(text, success) {
    try {
      await navigator.clipboard.writeText(text);
      announce(success);
    } catch {
      const fallback = dialog.querySelector('.copy-fallback');
      fallback.value = text;
      fallback.hidden = false;
      fallback.focus();
      fallback.select();
      announce('Your browser blocked copying.');
    }
  }

  function navigationPool() {
    const visible = viewRecords().filter(record => !record.element.hidden);
    return current && visible.includes(current) ? visible : current ? [current] : [];
  }

  function updateNavigation() {
    const pool = navigationPool();
    const index = pool.indexOf(current);
    dialog.querySelector('[data-paper-position]').textContent = (index + 1) + ' of ' + pool.length;
    dialog.querySelector('[data-paper-previous]').disabled = index <= 0;
    dialog.querySelector('[data-paper-next]').disabled = index >= pool.length - 1;
  }

  function updateRelated(record) {
    const related = records.filter(candidate => candidate !== record)
      .map(candidate => ({ candidate, shared: candidate.tags.filter(tag => record.tags.includes(tag)).length }))
      .filter(item => item.shared > 0)
      .sort((a, b) => b.shared - a.shared || Number(b.candidate.year) - Number(a.candidate.year))
      .slice(0, 3);
    dialog.querySelector('.paper-related').hidden = related.length === 0;
    dialog.querySelector('[data-related-papers]').replaceChildren(...related.map(({ candidate }) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'related-paper';
      button.dataset.relatedPaper = candidate.id;
      button.setAttribute('aria-label', 'Open ' + candidate.title);
      if (candidate.image) {
        const thumbnail = document.createElement('img');
        thumbnail.src = candidate.image.src;
        thumbnail.alt = '';
        thumbnail.loading = 'lazy';
        button.append(thumbnail);
      }
      const caption = document.createElement('span');
      const venue = document.createElement('small');
      venue.textContent = candidate.venue;
      caption.append(venue, document.createTextNode(candidate.title));
      button.append(caption);
      button.addEventListener('click', () => openPaper(candidate));
      return button;
    }));
  }

  function explorePaper() {
    const pool = records.filter(record => !record.element.hidden);
    if (!pool.length) return;
    let candidates = pool.filter(record => !explored.has(record.id));
    if (!candidates.length) {
      explored.clear();
      candidates = pool.filter(record => pool.length === 1 || record.id !== lastExplored);
    }
    const record = candidates[Math.floor(Math.random() * candidates.length)];
    explored.add(record.id);
    lastExplored = record.id;
    openPaper(record);
  }

  function openPaper(record, updateURL = true) {
    if (!canOpenDialog) return;
    if (!dialog.open) opener = document.activeElement;
    current = record;
    swipeStart = null;
    dialog.querySelector('#paper-dialog-title').textContent = record.title;
    dialog.querySelector('[data-paper-venue]').textContent = record.venue;
    dialog.querySelector('[data-paper-authors]').textContent = record.authors.join(', ');
    dialog.querySelector('[data-paper-citation]').textContent = citation(record);
    dialog.querySelector('[data-paper-links]').replaceChildren(...record.links.map(link => {
      const copy = link.cloneNode(true);
      copy.target = '_blank';
      copy.rel = 'noopener';
      return copy;
    }));
    const metrics = record.element.querySelector('.publication-citations');
    const metricsOutput = dialog.querySelector('[data-paper-metrics]');
    metricsOutput.hidden = !metrics;
    metricsOutput.textContent = metrics ? clean(metrics.textContent) + '.' + (metrics.dataset.recorded ? ' Recorded ' + metrics.dataset.recorded + '.' : '') : '';
    const figure = dialog.querySelector('.paper-figure');
    const viewport = dialog.querySelector('.paper-figure-viewport');
    const image = figure.querySelector('img');
    figure.hidden = !record.image;
    viewport.classList.remove('is-zoomed');
    viewport.scrollTo(0, 0);
    if (record.image) { image.src = record.image.src; image.alt = record.image.alt; } else image.removeAttribute('src');
    const source = dialog.querySelector('[data-paper-figure-source]');
    source.hidden = !record.element.dataset.imageSource;
    if (!source.hidden) source.href = record.element.dataset.imageSource;
    const zoom = dialog.querySelector('[data-paper-zoom]');
    zoom.setAttribute('aria-pressed', 'false');
    zoom.title = zoom.ariaLabel = 'Zoom figure';
    zoom.querySelector('i').className = 'fas fa-search-plus';
    dialog.querySelector('.paper-citation').open = false;
    dialog.querySelector('.copy-fallback').hidden = true;
    dialog.querySelector('[data-paper-status]').textContent = '';
    updateSaveButtons();
    updateNavigation();
    updateRelated(record);
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add('paper-is-open');
    dialog.scrollTop = 0;
    dialog.querySelector('#paper-dialog-title').focus({ preventScroll: true });
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches && typeof image.animate === 'function' && record.image) {
      image.getAnimations().forEach(animation => animation.cancel());
      image.animate([{ opacity: .35 }, { opacity: 1 }], { duration: 220, easing: 'ease-out' });
    }
    if (updateURL) {
      const url = new URL(location.href);
      url.searchParams.set('paper', record.id);
      history.replaceState(null, '', url);
    }
  }

  function navigatePaper(delta) {
    const pool = navigationPool();
    const next = pool[pool.indexOf(current) + delta];
    if (next) openPaper(next);
  }

  document.addEventListener('open-publication', event => {
    const record = byId.get(event.detail?.id);
    if (record) openPaper(record);
  });
  document.addEventListener('filter-publications', event => {
    const { topic, selectedYear } = event.detail || {};
    if (!topics.some(button => button.dataset.publicationFilter === topic) || !years.includes(selectedYear)) return;
    state.topic = topic; state.year = selectedYear; state.q = ''; state.saved = false;
    input.value = ''; year.value = selectedYear; changed();
    section.querySelector('[data-publication-count]').scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  });

  records.forEach(record => {
    const save = record.element.querySelector('[data-save-publication]');
    save.hidden = false;
    save.addEventListener('click', () => toggleSaved(record));
    if (!canOpenDialog) return;
    const title = record.element.querySelector('.publication-title');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'paper-title-button';
    button.textContent = record.title;
    button.setAttribute('aria-haspopup', 'dialog');
    button.addEventListener('click', () => openPaper(record));
    title.replaceChildren(button);
    if (record.image) {
      const imageButton = document.createElement('button');
      imageButton.type = 'button';
      imageButton.className = 'paper-image-button';
      imageButton.setAttribute('aria-label', 'Open figure and details for ' + record.title);
      imageButton.setAttribute('aria-haspopup', 'dialog');
      record.image.replaceWith(imageButton);
      imageButton.append(record.image);
      imageButton.addEventListener('click', () => openPaper(record));
    }
  });
  topics.forEach(button => button.addEventListener('click', () => { state.topic = button.dataset.publicationFilter; changed(); }));
  views.forEach(button => button.addEventListener('click', () => { state.view = button.dataset.publicationView; changed(); }));
  input.maxLength = 300;
  input.addEventListener('input', () => { state.q = input.value; changed(); });
  year.addEventListener('change', () => { state.year = year.value; changed(); });
  savedFilter.addEventListener('click', () => { state.saved = !state.saved; changed(); });
  section.querySelector('[data-reset-publications]').addEventListener('click', () => {
    state.topic = state.year = 'all'; state.q = ''; state.saved = false;
    input.value = ''; year.value = 'all'; changed();
  });
  section.querySelector('[data-download-saved]').addEventListener('click', () => {
    if (saved.size) download(records.filter(record => saved.has(record.id)).map(citation).join('\n\n'), 'srijit-seal-reading-list.txt');
  });
  document.querySelectorAll('[data-publication-topic]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    state.topic = link.dataset.publicationTopic;
    state.q = ''; state.saved = false; state.year = 'all';
    input.value = ''; year.value = 'all'; changed();
    section.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }));

  if (canOpenDialog) {
    exploreButton.hidden = false;
    exploreButton.addEventListener('click', explorePaper);
    dialog.querySelector('[data-paper-close]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog && event.clientX < dialog.getBoundingClientRect().left) dialog.close(); });
    dialog.addEventListener('close', () => {
      if (dialog.open) return;
      document.documentElement.classList.remove('paper-is-open');
      const url = new URL(location.href);
      url.searchParams.delete('paper');
      history.replaceState(null, '', url);
      if (opener && opener.isConnected && opener.getClientRects().length) opener.focus({ preventScroll: true });
      else input.focus({ preventScroll: true });
      current = null;
    });
    dialog.querySelector('[data-paper-previous]').addEventListener('click', () => navigatePaper(-1));
    dialog.querySelector('[data-paper-next]').addEventListener('click', () => navigatePaper(1));
    const figureViewport = dialog.querySelector('.paper-figure-viewport');
    figureViewport.addEventListener('pointerdown', event => {
      swipeStart = event.isPrimary && event.pointerType === 'touch' && !figureViewport.classList.contains('is-zoomed')
        ? { id: event.pointerId, x: event.clientX, y: event.clientY } : null;
    });
    figureViewport.addEventListener('pointercancel', () => { swipeStart = null; });
    figureViewport.addEventListener('pointerup', event => {
      const start = swipeStart;
      swipeStart = null;
      if (!start || start.id !== event.pointerId || figureViewport.classList.contains('is-zoomed')) return;
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (Math.abs(dx) >= 64 && Math.abs(dx) > Math.abs(dy) * 2) navigatePaper(dx < 0 ? 1 : -1);
    });
    dialog.addEventListener('keydown', event => {
      if (event.target.matches('input, textarea') || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        if (event.target.closest('.paper-figure-viewport')) return;
        event.preventDefault(); navigatePaper(event.key === 'ArrowRight' ? 1 : -1);
      }
    });
    dialog.querySelector('[data-paper-save]').addEventListener('click', () => { if (current) toggleSaved(current); });
    dialog.querySelector('[data-copy-citation]').addEventListener('click', () => { if (current) copy(citation(current), 'Citation copied.'); });
    dialog.querySelector('[data-copy-paper-link]').addEventListener('click', () => {
      if (!current) return;
      const url = new URL(location.pathname, location.origin);
      url.searchParams.set('paper', current.id); url.hash = 'publications';
      copy(url.href, 'Publication link copied.');
    });
    dialog.querySelector('[data-download-citation]').addEventListener('click', () => {
      if (current) download(citation(current), current.id.replace(/[^a-zA-Z0-9_-]/g, '-') + '-citation.txt');
    });
    dialog.querySelector('[data-paper-zoom]').addEventListener('click', event => {
      const zoomed = dialog.querySelector('.paper-figure-viewport').classList.toggle('is-zoomed');
      event.currentTarget.setAttribute('aria-pressed', String(zoomed));
      event.currentTarget.title = event.currentTarget.ariaLabel = zoomed ? 'Fit figure' : 'Zoom figure';
      event.currentTarget.querySelector('i').className = 'fas ' + (zoomed ? 'fa-compress' : 'fa-search-plus');
    });
  }
  addEventListener('storage', event => {
    if (event.key === storageKey || event.key === null) { saved = readSaved(); apply(); if (current && dialog.open) updateNavigation(); }
  });
  addEventListener('popstate', () => {
    readState(); apply(true);
    const record = byId.get(new URL(location.href).searchParams.get('paper'));
    if (record) openPaper(record, false); else if (canOpenDialog && dialog.open) dialog.close();
  });
  readState();
  apply(true);
  section.querySelector('.publication-toolbar').hidden = false;
  section.querySelector('.publication-results-heading').hidden = false;
  section.querySelector('.filter-bar').hidden = false;
  const linkedPaper = byId.get(new URL(location.href).searchParams.get('paper'));
  if (linkedPaper) openPaper(linkedPaper, false);
})();
