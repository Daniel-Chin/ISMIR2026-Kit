(() => {
  const STORAGE_KEY = 'ismir-attendee-cursor-role';
  const roles = [
    { id: 'reader', label: 'Paper detective', hint: 'magnifier + paper', colors: { shirt: '#28e6ff', hair: '#4a2a18', accent: '#ffe76a' } },
    { id: 'tech', label: 'Tech guy', hint: 'console + circuits', colors: { shirt: '#37f6a5', hair: '#222a44', accent: '#28e6ff' } },
    { id: 'phd', label: 'PhD cap', hint: 'doctoral mode', colors: { shirt: '#8c6cff', hair: '#24223a', accent: '#ffe76a' } },
    { id: 'drummer', label: 'Drummer', hint: 'sticks + snare', colors: { shirt: '#ff7b39', hair: '#3d2b18', accent: '#28e6ff' } },
    { id: 'guitarist', label: 'Guitarist', hint: 'pixel guitar', colors: { shirt: '#2ee86d', hair: '#4a2418', accent: '#ffb13d' } },
    { id: 'pianist', label: 'Pianist', hint: 'mini keyboard', colors: { shirt: '#f7f2dc', hair: '#282c44', accent: '#28e6ff' } },
    { id: 'violinist', label: 'Violinist', hint: 'violin + bow', colors: { shirt: '#ffd24a', hair: '#4c2a16', accent: '#ff5ec4' } },
    { id: 'none', label: 'None', hint: 'hide avatar', colors: { shirt: '#dbe7ff', hair: '#26304f', accent: '#ffe76a' } }
  ];

  const roleById = Object.fromEntries(roles.map((r) => [r.id, r]));
  const savedRole = localStorage.getItem(STORAGE_KEY);
  const migratedRole = savedRole === 'boy' ? 'tech' : savedRole === 'girl' ? 'none' : savedRole === 'random' ? 'none' : savedRole;
  let currentRole = roleById[migratedRole] || roleById.none;
  if (savedRole !== migratedRole && migratedRole) localStorage.setItem(STORAGE_KEY, migratedRole);
  let lastX = window.innerWidth / 2;
  let lastY = window.innerHeight / 2;
  let raf = 0;

  const cursor = document.createElement('div');
  cursor.className = 'attendee-cursor is-ready';
  cursor.dataset.role = currentRole.id;
  cursor.classList.toggle('is-hidden', currentRole.id === 'none');
  cursor.setAttribute('aria-hidden', 'true');
  cursor.innerHTML = currentRole.id === 'none' ? '' : sprite(currentRole);

  const badge = document.createElement('div');
  badge.className = 'attendee-role-badge';
  badge.textContent = currentRole.id === 'none' ? '' : currentRole.label;
  if (currentRole.id !== 'none') cursor.appendChild(badge);

  const menu = document.createElement('div');
  menu.className = 'attendee-role-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'Choose attendee cursor role');
  menu.innerHTML = `
    <div class="attendee-menu-title">Choose attendee avatar</div>
    <div class="attendee-menu-grid">
      ${roles.map((role) => `
        <button type="button" class="attendee-role-option" data-role="${role.id}" role="menuitem">
          <span class="attendee-role-mini" aria-hidden="true">${sprite(role, true)}</span>
          <span><strong>${escapeHtml(role.label)}</strong><small>${escapeHtml(role.hint)}</small></span>
        </button>
      `).join('')}
    </div>
    <div class="attendee-menu-help">Press R to switch avatar · Esc closes</div>
  `;

  document.body.appendChild(cursor);
  document.body.appendChild(menu);
  setActiveOption();

  window.addEventListener('pointermove', (event) => {
    lastX = event.clientX;
    lastY = event.clientY;
    if (!raf) raf = requestAnimationFrame(updateCursorPosition);
  }, { passive: true });

  window.addEventListener('pointerdown', (event) => {
    if (menu.contains(event.target)) return;
    hideMenu();
  }, { passive: true });


  menu.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
  });

  menu.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const button = event.target.closest('[data-role]');
    if (!button) return;
    const role = roleById[button.dataset.role];
    if (!role) return;
    setRole(role);
    hideMenu();
  });

  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') hideMenu();
    if ((event.key === 'r' || event.key === 'R') && !isTypingTarget(document.activeElement)) {
      const idx = roles.findIndex((role) => role.id === currentRole.id);
      setRole(roles[(idx + 1) % roles.length]);
    }
  });

  window.addEventListener('blur', hideMenu);


  function isTypingTarget(target) {
    return Boolean(target && target.closest && target.closest('input, textarea, select, [contenteditable="true"]'));
  }

  function updateCursorPosition() {
    raf = 0;
    const offsetX = 16;
    const offsetY = 14;
    const maxX = window.innerWidth - 72;
    const maxY = window.innerHeight - 78;
    const x = Math.min(Math.max(8, lastX + offsetX), maxX);
    const y = Math.min(Math.max(8, lastY + offsetY), maxY);
    cursor.style.transform = `translate3d(${x}px, ${y}px, 0)`;
  }

  function showMenu(x, y) {
    const pad = 12;
    menu.classList.add('is-open');
    menu.style.visibility = 'hidden';
    menu.style.left = '0px';
    menu.style.top = '0px';
    const rect = menu.getBoundingClientRect();
    const left = Math.min(Math.max(pad, x), window.innerWidth - rect.width - pad);
    const top = Math.min(Math.max(pad, y), window.innerHeight - rect.height - pad);
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
    menu.style.visibility = 'visible';
  }

  function hideMenu() {
    menu.classList.remove('is-open');
    menu.style.visibility = '';
  }

  function setRole(role) {
    currentRole = role;
    localStorage.setItem(STORAGE_KEY, role.id);
    cursor.dataset.role = role.id;
    cursor.classList.toggle('is-hidden', role.id === 'none');

    if (role.id === 'none') {
      cursor.innerHTML = '';
      badge.textContent = '';
      setActiveOption();
      return;
    }

    cursor.innerHTML = sprite(role);
    cursor.appendChild(badge);
    badge.textContent = role.label;
    setActiveOption();
    cursor.animate([
      { transform: cursor.style.transform + ' scale(1)' },
      { transform: cursor.style.transform + ' scale(1.16)' },
      { transform: cursor.style.transform + ' scale(1)' }
    ], { duration: 180, easing: 'steps(3, end)' });
  }

  function setActiveOption() {
    menu.querySelectorAll('[data-role]').forEach((button) => {
      button.classList.toggle('is-active', button.dataset.role === currentRole.id);
    });
  }

  function sprite(role, mini = false) {
    if (role.id === 'none') return noneSprite(mini);
    const c = role.colors;
    const px = mini ? 1 : 1;
    const common = [
      rect(13, 4, 6, 2, c.hair),
      rect(11, 6, 10, 7, '#f2b083'),
      rect(12, 7, 2, 2, '#101426'),
      rect(18, 7, 2, 2, '#101426'),
      rect(14, 11, 4, 1, '#9d4f45'),
      rect(10, 13, 12, 8, c.shirt),
      rect(8, 14, 3, 7, c.shirt),
      rect(21, 14, 3, 7, c.shirt),
      rect(12, 21, 3, 6, '#1a2852'),
      rect(17, 21, 3, 6, '#1a2852'),
      rect(10, 27, 5, 2, '#111525'),
      rect(17, 27, 5, 2, '#111525')
    ];

    const extras = {
      reader: [
        rect(23, 7, 5, 6, '#f8f4d8'), rect(24, 8, 3, 1, '#26304f'), rect(24, 10, 3, 1, '#26304f'),
        rect(5, 8, 5, 5, 'none', c.accent), rect(9, 12, 4, 2, c.accent), rect(8, 9, 1, 1, c.accent)
      ],
      tech: [rect(7, 3, 18, 3, '#14172a'), rect(8, 2, 16, 1, c.accent), rect(23, 6, 4, 3, '#111525'), rect(24, 7, 1, 1, '#28e6ff'), rect(26, 17, 3, 7, '#26304f'), rect(27, 18, 1, 1, c.accent), rect(4, 17, 5, 2, c.accent)],
      phd: [rect(8, 3, 16, 2, '#14172a'), rect(14, 1, 4, 2, '#14172a'), rect(22, 4, 1, 5, c.accent), rect(23, 8, 2, 2, c.accent)],
      drummer: [rect(5, 21, 22, 5, '#dce8ff'), rect(5, 20, 22, 2, c.accent), rect(8, 18, 2, 7, '#f8f4d8'), rect(23, 17, 2, 8, '#f8f4d8'), rect(3, 12, 8, 2, c.accent), rect(21, 12, 8, 2, c.accent)],
      guitarist: [rect(22, 12, 3, 15, '#6c3a18'), rect(19, 19, 8, 7, c.accent), rect(21, 21, 2, 2, '#101426'), rect(25, 10, 5, 3, '#6c3a18'), rect(6, 18, 5, 2, c.accent)],
      pianist: [rect(5, 22, 22, 5, '#f8f4d8'), rect(5, 21, 22, 2, '#101426'), rect(9, 22, 2, 5, '#101426'), rect(14, 22, 2, 5, '#101426'), rect(21, 22, 2, 5, '#101426')],
      violinist: [rect(22, 15, 6, 9, '#9b5a20'), rect(24, 17, 2, 2, '#101426'), rect(27, 12, 2, 12, '#6c3a18'), rect(5, 16, 15, 2, c.accent), rect(4, 13, 2, 8, '#f8f4d8')]
    }[role.id] || [];

    return `<svg class="attendee-sprite${mini ? ' attendee-sprite-mini' : ''}" viewBox="0 0 32 32" width="${mini ? 32 : 56}" height="${mini ? 32 : 56}" aria-hidden="true" shape-rendering="crispEdges">
      <rect x="0" y="0" width="32" height="32" fill="rgba(7,10,24,.72)"/>
      <rect x="1" y="1" width="30" height="30" fill="rgba(14,23,55,.82)" stroke="#28e6ff" stroke-width="1"/>
      ${common.join('')}
      ${extras.join('')}
      <rect x="4" y="4" width="3" height="3" fill="${c.accent}" opacity=".9"/>
      <rect x="25" y="4" width="3" height="3" fill="#ff5ec4" opacity=".85"/>
      <rect x="4" y="25" width="3" height="3" fill="#ffe76a" opacity=".9"/>
    </svg>`;
  }


  function noneSprite(mini = false) {
    return `<svg class="attendee-sprite${mini ? ' attendee-sprite-mini' : ''} attendee-sprite-none" viewBox="0 0 32 32" width="${mini ? 32 : 56}" height="${mini ? 32 : 56}" aria-hidden="true" shape-rendering="crispEdges">
      <rect x="0" y="0" width="32" height="32" fill="rgba(7,10,24,.72)"/>
      <rect x="1" y="1" width="30" height="30" fill="rgba(14,23,55,.82)" stroke="#ffe76a" stroke-width="1"/>
      <rect x="8" y="8" width="16" height="16" fill="none" stroke="#28e6ff" stroke-width="3"/>
      <rect x="11" y="11" width="10" height="10" fill="rgba(255,94,196,.16)"/>
      <rect x="10" y="10" width="3" height="3" fill="#ff5ec4"/>
      <rect x="19" y="10" width="3" height="3" fill="#ff5ec4"/>
      <rect x="13" y="19" width="6" height="2" fill="#ffe76a"/>
      <rect x="6" y="6" width="3" height="3" fill="#ffe76a"/>
      <rect x="23" y="23" width="3" height="3" fill="#28e6ff"/>
    </svg>`;
  }

  function rect(x, y, w, h, fill, stroke) {
    const attrs = [`x="${x}"`, `y="${y}"`, `width="${w}"`, `height="${h}"`];
    if (fill && fill !== 'none') attrs.push(`fill="${fill}"`);
    else attrs.push('fill="none"');
    if (stroke) attrs.push(`stroke="${stroke}"`, 'stroke-width="1"');
    return `<rect ${attrs.join(' ')}/>`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  }
})();
