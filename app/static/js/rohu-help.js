/* ROHU Contable — Help System (contextual drawer + keyboard shortcut) */

const ROHU_HELP = {
  dashboard: {
    title: 'Tablero de Control',
    tagline: 'Tu negocio de un vistazo',
    steps: [
      'Aquí ves el resumen del día: ventas, gastos y alertas de inventario.',
      'Usa los filtros de fecha (Hoy, Ayer, Semana, Mes) para ver otros periodos.',
      'Las gráficas muestran ventas por hora y métodos de pago.',
      'Los productos más vendidos aparecen con su margen de utilidad.',
    ],
    tip: 'El tablero se actualiza cada vez que cambias el filtro de fecha.',
  },
  pos: {
    title: 'Punto de Venta',
    tagline: 'Cobra rápido y sin errores',
    steps: [
      'Busque el producto por nombre o escanee el código de barras.',
      'Haga clic en el producto para agregarlo al carrito.',
      'Ajuste la cantidad si necesita más de uno.',
      'Seleccione la forma de pago (efectivo, tarjeta, Nequi, etc.).',
      'Confirme la venta y entregue el recibo al cliente.',
    ],
    tip: 'Para ventas a crédito, seleccione "Crédito" como tipo de venta y elija el cliente.',
  },
  inventory: {
    title: 'Inventario',
    tagline: 'Controla lo que tienes',
    steps: [
      'Vea todos sus productos con stock, precio de venta y costo.',
      'Use "+ Nuevo Producto" para agregar productos uno a uno.',
      'Use "Importar Factura" para agregar varios productos desde una foto de factura (OCR).',
      'El botón "+Stock" permite agregar inventario rápidamente.',
      'Los productos con stock bajo aparecen marcados en rojo.',
    ],
    tip: 'Active el "Modo continuo" al crear productos para registrar varios seguidos sin cerrar el formulario.',
  },
  purchases: {
    title: 'Compras y Proveedores',
    tagline: 'Registra lo que compraste',
    steps: [
      'Cree una Orden de Compra seleccionando proveedor y productos.',
      'Al recibir la mercancía, marque la OC como "Recibida" — el inventario se actualiza automáticamente.',
      'En la pestaña "Pagos" registre los pagos a proveedores.',
      'Use "NC/ND" para devoluciones o cargos adicionales.',
      'El "Estado de Cuenta" muestra cuánto le debe a cada proveedor.',
    ],
    tip: 'Las compras a crédito se reflejan automáticamente en el balance de Cuentas por Pagar.',
  },
  suppliers: {
    title: 'Proveedores',
    tagline: 'Los que te venden',
    steps: [
      'Registre los datos de sus proveedores (nombre, NIT, teléfono).',
      'Configure los días de crédito que cada proveedor le da.',
      'Desde aquí puede ver las compras y el estado de cuenta de cada proveedor.',
    ],
    tip: 'Tener los proveedores registrados le permite crear órdenes de compra más rápido.',
  },
  customers: {
    title: 'Clientes',
    tagline: 'Los que te compran',
    steps: [
      'Registre clientes para ventas a crédito y facturación.',
      'Configure el límite de crédito y días de plazo por cliente.',
      'Use "Carta Cobro" para generar una carta formal de cobro imprimible.',
    ],
    tip: 'Los clientes con deuda vencida aparecen resaltados en el módulo de Cobro Cartera.',
  },
  campaigns: {
    title: 'Cobro de Cartera',
    tagline: 'Lo que te deben',
    steps: [
      'Cree una campaña de cobro para contactar clientes morosos.',
      'Active la campaña para generar los mensajes personalizados.',
      'Envíe los mensajes por WhatsApp, email o imprima la carta de cobro.',
      'Registre si el cliente prometió pagar o ya pagó.',
    ],
    tip: 'También puede generar cartas de cobro directamente desde la lista de Clientes.',
  },
  cash: {
    title: 'Caja y Bancos',
    tagline: 'Tu plata día a día',
    steps: [
      'Registre ingresos de caja (pagos de clientes, capital, etc.).',
      'Registre egresos (pagos a proveedores, gastos operativos, etc.).',
      'Use "Traslados" para mover dinero entre caja y bancos.',
      'Cada operación genera automáticamente el asiento contable.',
    ],
    tip: 'Los recibos y egresos se reflejan inmediatamente en el flujo de caja del tablero.',
  },
  reports: {
    title: 'Reportes',
    tagline: 'Números claros',
    steps: [
      'Seleccione el rango de fechas para filtrar los reportes.',
      'Vea ventas por producto, por día o por método de pago.',
      'Exporte a CSV para abrir en Excel.',
    ],
    tip: 'Los reportes son útiles para preparar la declaración de renta e IVA.',
  },
  analytics: {
    title: 'Análisis de Negocio',
    tagline: 'Tendencias de tu negocio',
    steps: [
      'Vea la utilidad bruta por periodo (diario o mensual).',
      'El flujo de caja muestra ingresos vs egresos en el tiempo.',
      'Los márgenes por producto le ayudan a identificar qué vender más.',
      'Use los filtros de periodo (30, 90, 180 días, 1 año) para comparar.',
    ],
    tip: 'Los productos sin movimiento en +30 días aparecen como "stock muerto" — considere hacer descuento.',
  },
  invoicing: {
    title: 'Facturación Electrónica',
    tagline: 'Facturas para la DIAN',
    steps: [
      'Configure su proveedor tecnológico (PTA) en Administración > Mi Negocio.',
      'Las facturas se generan automáticamente al realizar ventas.',
      'Envíe las facturas por correo electrónico al cliente.',
    ],
    tip: 'Requiere resolución de facturación de la DIAN y un proveedor tecnológico autorizado.',
  },
  financial: {
    title: 'Estados Financieros',
    tagline: 'Balance y resultados',
    steps: [
      'Seleccione el año y mes para generar los estados financieros.',
      'El Estado de Resultados muestra ingresos menos gastos (acumulado del año).',
      'El Balance de Prueba muestra todas las cuentas con sus saldos.',
      'Use "Imprimir" para generar una versión para su contador.',
    ],
    tip: 'Estos reportes son de soporte. Los estados financieros certificados los firma un contador público.',
  },
  reports_dian: {
    title: 'Soporte DIAN',
    tagline: 'Reportes para impuestos',
    steps: [
      'Seleccione el año y el bimestre para generar el reporte de IVA.',
      'Vea el resumen de IVA generado y IVA descontable.',
      'El resumen tributario anual le ayuda a preparar la declaración de renta.',
    ],
    tip: 'Consulte con su contador antes de presentar declaraciones ante la DIAN.',
  },
  accounting: {
    title: 'Contabilidad',
    tagline: 'El libro de cuentas',
    steps: [
      'El Balance de Prueba muestra todas las cuentas con débitos y créditos.',
      'El Libro Diario muestra todos los asientos contables.',
      'En Plan de Cuentas (PUC) puede ver, crear o inactivar cuentas.',
      'En Periodos/Cierre puede cerrar meses para evitar modificaciones.',
    ],
    tip: 'Cerrar un mes es como "congelar" ese periodo. Solo diciembre genera el asiento de cierre anual.',
  },
  admin_settings: {
    title: 'Configuración del Negocio',
    tagline: 'Datos de tu empresa',
    steps: [
      'Configure nombre, NIT, dirección y datos de contacto.',
      'Configure el correo SMTP para enviar facturas y cartas por email.',
      'Vea el estado de salud del sistema en la sección "Estado del Sistema".',
    ],
    tip: 'Complete todos los datos para que las facturas y cartas de cobro tengan membrete completo.',
  },
  admin_users: {
    title: 'Usuarios y Roles',
    tagline: 'Quién puede hacer qué',
    steps: [
      'Cree usuarios para sus empleados (cajeros, contadores, etc.).',
      'Asigne roles para controlar qué módulos puede ver cada usuario.',
      'Cree roles personalizados con permisos específicos.',
    ],
    tip: 'El rol "Cajero" solo ve el POS. El rol "Contador" ve reportes y contabilidad.',
  },
};

// ── Help Drawer ──────────────────────────────────────────────
let helpDrawerCreated = false;

function getActivePage() {
  return document.body.dataset.activePage || 'dashboard';
}

function createHelpDrawer() {
  if (helpDrawerCreated) return;
  helpDrawerCreated = true;

  const overlay = document.createElement('div');
  overlay.id = 'help-overlay';
  overlay.className = 'help-overlay';
  overlay.onclick = closeHelp;

  const drawer = document.createElement('aside');
  drawer.id = 'help-drawer';
  drawer.className = 'help-drawer';
  drawer.innerHTML = `
    <div class="help-drawer-header">
      <span style="font-weight:700;font-size:16px;">Ayuda</span>
      <button onclick="closeHelp()" style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-light);">&times;</button>
    </div>
    <div class="help-drawer-tabs">
      <button class="help-tab active" onclick="showHelpTab('current')">Este módulo</button>
      <button class="help-tab" onclick="showHelpTab('all')">Todos</button>
    </div>
    <div id="help-content" class="help-drawer-body"></div>
    <div class="help-drawer-footer">
      <a href="/app/help" style="color:var(--primary);font-size:13px;text-decoration:none;">Ver guía completa &rarr;</a>
    </div>
  `;

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);
}

function toggleHelp() {
  createHelpDrawer();
  const drawer = document.getElementById('help-drawer');
  const overlay = document.getElementById('help-overlay');
  const isOpen = drawer.classList.toggle('open');
  overlay.classList.toggle('active', isOpen);
  if (isOpen) showHelpTab('current');
}

function closeHelp() {
  const drawer = document.getElementById('help-drawer');
  const overlay = document.getElementById('help-overlay');
  if (drawer) drawer.classList.remove('open');
  if (overlay) overlay.classList.remove('active');
}

function showHelpTab(tab) {
  document.querySelectorAll('.help-tab').forEach((b, i) => {
    b.classList.toggle('active', (tab === 'current' && i === 0) || (tab === 'all' && i === 1));
  });

  const content = document.getElementById('help-content');
  if (tab === 'current') {
    const page = getActivePage();
    const h = ROHU_HELP[page] || ROHU_HELP['dashboard'];
    content.innerHTML = renderHelpModule(h);
  } else {
    content.innerHTML = Object.values(ROHU_HELP).map(h => `
      <details style="margin-bottom:8px;">
        <summary style="cursor:pointer;padding:10px;background:var(--bg);border-radius:6px;font-weight:600;font-size:14px;">${h.title} <span style="font-weight:400;color:var(--text-light);font-size:12px;">— ${h.tagline}</span></summary>
        <div style="padding:8px 12px;">${renderHelpModule(h)}</div>
      </details>
    `).join('');
  }
}

function renderHelpModule(h) {
  return `
    <h3 style="font-size:16px;margin-bottom:4px;">${h.title}</h3>
    <p style="color:var(--text-light);font-size:13px;margin-bottom:12px;">${h.tagline}</p>
    <div style="font-size:13px;line-height:1.8;">
      <strong>Cómo usarlo:</strong>
      <ol style="padding-left:20px;margin:8px 0;">
        ${h.steps.map(s => `<li>${s}</li>`).join('')}
      </ol>
      ${h.tip ? `<div style="background:#FEF3C7;padding:8px 12px;border-radius:6px;margin-top:8px;font-size:12px;"><strong>Consejo:</strong> ${h.tip}</div>` : ''}
    </div>
  `;
}

// Keyboard shortcut: F1
document.addEventListener('keydown', e => {
  if (e.key === 'F1') { e.preventDefault(); toggleHelp(); }
  if (e.key === 'Escape') closeHelp();
});
