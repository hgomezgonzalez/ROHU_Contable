/**
 * ROHU Contable — Custom Modal System
 * Replaces native alert(), confirm(), prompt() with branded modals.
 * Usage:
 *   await rohuAlert('Mensaje', 'success')     // types: success, error, warning, info
 *   const ok = await rohuConfirm('¿Seguro?')  // returns true/false
 *   const val = await rohuPrompt('Texto:', 'placeholder')  // returns string or null
 */

(function() {
  const ICONS = {
    success: '<div style="width:64px;height:64px;border-radius:50%;background:#D1FAE5;display:flex;align-items:center;justify-content:center;margin:0 auto;"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#22C55E" stroke-width="2.5"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div>',
    error: '<div style="width:64px;height:64px;border-radius:50%;background:#FEE2E2;display:flex;align-items:center;justify-content:center;margin:0 auto;"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg></div>',
    warning: '<div style="width:64px;height:64px;border-radius:50%;background:#FEF3C7;display:flex;align-items:center;justify-content:center;margin:0 auto;"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#F59E0B" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div>',
    info: '<div style="width:64px;height:64px;border-radius:50%;background:#DBEAFE;display:flex;align-items:center;justify-content:center;margin:0 auto;"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#1E3A8A" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></div>',
  };

  const TITLES = {success:'Operación exitosa', error:'Error', warning:'Atención', info:'Información'};
  const COLORS = {success:'#22C55E', error:'#EF4444', warning:'#F59E0B', info:'#1E3A8A'};

  function createOverlay() {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,0.6);z-index:9999;display:flex;align-items:center;justify-content:center;animation:rohuFadeIn 0.2s ease;';
    return overlay;
  }

  function createCard() {
    const card = document.createElement('div');
    card.style.cssText = 'background:white;border-radius:16px;padding:0;width:100%;max-width:420px;box-shadow:0 25px 60px rgba(0,0,0,0.25);text-align:center;animation:rohuSlideUp 0.25s ease;overflow:hidden;';
    // Corporate top bar
    const bar = document.createElement('div');
    bar.style.cssText = 'height:4px;background:linear-gradient(90deg,#1E3A8A,#10B981,#06B6D4);';
    card.appendChild(bar);
    // Content wrapper
    const content = document.createElement('div');
    content.style.cssText = 'padding:28px 28px 24px;';
    card._content = content;
    card.appendChild(content);
    // Override innerHTML to write to content
    const origSet = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML').set;
    Object.defineProperty(card, 'innerHTML', {
      set: function(v) { origSet.call(content, v); },
      get: function() { return content.innerHTML; },
    });
    // Override appendChild to add to content
    const origAppend = card.appendChild.bind(card);
    card.appendChild = function(child) { content.appendChild(child); return child; };
    return card;
  }

  function createButton(text, primary, color) {
    const btn = document.createElement('button');
    btn.textContent = text;
    if (primary) {
      btn.style.cssText = `padding:10px 24px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;background:${color||'#1E3A8A'};color:white;min-width:100px;transition:opacity 0.2s;`;
      btn.onmouseenter = () => btn.style.opacity = '0.85';
      btn.onmouseleave = () => btn.style.opacity = '1';
    } else {
      btn.style.cssText = 'padding:10px 24px;border:1px solid #E2E8F0;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;background:white;color:#0F172A;min-width:100px;transition:background 0.2s;';
      btn.onmouseenter = () => btn.style.background = '#F1F5F9';
      btn.onmouseleave = () => btn.style.background = 'white';
    }
    return btn;
  }

  // Inject animation CSS once
  if (!document.getElementById('rohu-modal-styles')) {
    const style = document.createElement('style');
    style.id = 'rohu-modal-styles';
    style.textContent = `
      @keyframes rohuFadeIn { from{opacity:0} to{opacity:1} }
      @keyframes rohuSlideUp { from{transform:translateY(20px);opacity:0} to{transform:translateY(0);opacity:1} }
    `;
    document.head.appendChild(style);
  }

  /**
   * rohuAlert — branded alert modal
   * @param {string} message
   * @param {string} type — 'success'|'error'|'warning'|'info'
   * @returns {Promise<void>}
   */
  window.rohuAlert = function(message, type = 'info') {
    return new Promise(resolve => {
      const overlay = createOverlay();
      const card = createCard();

      card.innerHTML = `
        <div style="margin-bottom:12px;">${ICONS[type] || ICONS.info}</div>
        <div style="font-weight:700;font-size:16px;color:${COLORS[type]||'#1E3A8A'};margin-bottom:8px;">${TITLES[type]||'Información'}</div>
        <div style="font-size:14px;color:#0F172A;margin-bottom:20px;line-height:1.6;">${message}</div>
      `;

      const btn = createButton('Aceptar', true, COLORS[type]);
      btn.onclick = () => { overlay.remove(); resolve(); };
      card.appendChild(btn);

      overlay.appendChild(card);
      document.body.appendChild(overlay);
      btn.focus();

      overlay.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === 'Escape') { overlay.remove(); resolve(); }
      });
    });
  };

  /**
   * rohuConfirm — branded confirm modal
   * @param {string} message
   * @param {string} confirmText
   * @param {string} type
   * @returns {Promise<boolean>}
   */
  window.rohuConfirm = function(message, confirmText = 'Confirmar', type = 'warning') {
    return new Promise(resolve => {
      const overlay = createOverlay();
      const card = createCard();

      card.innerHTML = `
        <div style="margin-bottom:12px;">${ICONS[type] || ICONS.warning}</div>
        <div style="font-weight:700;font-size:16px;color:${COLORS[type]||'#F59E0B'};margin-bottom:8px;">${TITLES[type]||'Confirmar'}</div>
        <div style="font-size:14px;color:#0F172A;margin-bottom:20px;line-height:1.6;">${message}</div>
      `;

      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:8px;justify-content:center;';

      const cancelBtn = createButton('Cancelar', false);
      cancelBtn.onclick = () => { overlay.remove(); resolve(false); };

      const okBtn = createButton(confirmText, true, COLORS[type]);
      okBtn.onclick = () => { overlay.remove(); resolve(true); };

      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(okBtn);
      card.appendChild(btnRow);

      overlay.appendChild(card);
      document.body.appendChild(overlay);
      okBtn.focus();

      overlay.addEventListener('keydown', e => {
        if (e.key === 'Escape') { overlay.remove(); resolve(false); }
        if (e.key === 'Enter') { overlay.remove(); resolve(true); }
      });
    });
  };

  /**
   * rohuPrompt — branded prompt modal with input
   * @param {string} message
   * @param {string} placeholder
   * @param {string} defaultValue
   * @param {string} inputType
   * @returns {Promise<string|null>}
   */
  window.rohuPrompt = function(message, placeholder = '', defaultValue = '', inputType = 'text') {
    return new Promise(resolve => {
      const overlay = createOverlay();
      const card = createCard();

      card.innerHTML = `
        <div style="margin-bottom:12px;">${ICONS.info}</div>
        <div style="font-weight:700;font-size:16px;color:#1E3A8A;margin-bottom:8px;">Ingrese datos</div>
        <div style="font-size:14px;color:#0F172A;margin-bottom:16px;line-height:1.6;">${message}</div>
      `;

      const input = document.createElement('input');
      input.type = inputType;
      input.placeholder = placeholder;
      input.value = defaultValue;
      input.style.cssText = 'width:100%;padding:10px 12px;border:1px solid #E2E8F0;border-radius:8px;font-size:14px;margin-bottom:16px;box-sizing:border-box;text-align:center;';
      card.appendChild(input);

      const btnRow = document.createElement('div');
      btnRow.style.cssText = 'display:flex;gap:8px;justify-content:center;';

      const cancelBtn = createButton('Cancelar', false);
      cancelBtn.onclick = () => { overlay.remove(); resolve(null); };

      const okBtn = createButton('Aceptar', true);
      okBtn.onclick = () => { overlay.remove(); resolve(input.value); };

      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(okBtn);
      card.appendChild(btnRow);

      overlay.appendChild(card);
      document.body.appendChild(overlay);
      input.focus();
      input.select();

      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { overlay.remove(); resolve(input.value); }
        if (e.key === 'Escape') { overlay.remove(); resolve(null); }
      });
    });
  };

  /**
   * rohuExpandChart — open a Chart.js canvas in fullscreen modal
   * @param {string} canvasId — the canvas element ID
   */
  window.rohuExpandChart = function(canvasId) {
    const srcCanvas = document.getElementById(canvasId);
    if (!srcCanvas) return;

    const overlay = createOverlay();
    const card = document.createElement('div');
    card.style.cssText = 'background:white;border-radius:12px;padding:20px;width:92vw;height:85vh;box-shadow:0 20px 60px rgba(0,0,0,0.3);display:flex;flex-direction:column;animation:rohuSlideUp 0.25s ease;';

    const header = document.createElement('div');
    header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;';
    header.innerHTML = '<span style="font-size:14px;font-weight:600;color:#0F172A;">Vista ampliada</span>';
    const closeBtn = createButton('Cerrar', false);
    closeBtn.onclick = () => overlay.remove();
    header.appendChild(closeBtn);
    card.appendChild(header);

    const wrapper = document.createElement('div');
    wrapper.style.cssText = 'flex:1;position:relative;';
    const newCanvas = document.createElement('canvas');
    wrapper.appendChild(newCanvas);
    card.appendChild(wrapper);

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    // Clone the chart config with full options restored for expanded view
    const chartInstance = Chart.getChart(srcCanvas);
    if (chartInstance) {
      const clonedOptions = JSON.parse(JSON.stringify(chartInstance.config.options));
      // Restore full display options for expanded view
      clonedOptions.responsive = true;
      clonedOptions.maintainAspectRatio = false;
      if (!clonedOptions.plugins) clonedOptions.plugins = {};
      clonedOptions.plugins.legend = { display: true, position: 'bottom' };
      // Restore scales (ticks, grid) for expanded view
      if (clonedOptions.scales) {
        Object.keys(clonedOptions.scales).forEach(axis => {
          if (clonedOptions.scales[axis].ticks) clonedOptions.scales[axis].ticks.display = true;
          if (clonedOptions.scales[axis].grid) clonedOptions.scales[axis].grid.display = true;
          if (clonedOptions.scales[axis].ticks && clonedOptions.scales[axis].ticks.font) {
            clonedOptions.scales[axis].ticks.font.size = 12;
          }
        });
      }
      // Restore point radius for line charts
      if (clonedOptions.elements && clonedOptions.elements.point) {
        clonedOptions.elements.point.radius = 4;
      }
      new Chart(newCanvas, {
        type: chartInstance.config.type,
        data: JSON.parse(JSON.stringify(chartInstance.config.data)),
        options: clonedOptions,
      });
    }

    overlay.addEventListener('keydown', e => {
      if (e.key === 'Escape') overlay.remove();
    });
    closeBtn.focus();
  };
})();
