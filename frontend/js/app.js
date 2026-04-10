/* ──────────────────────────────────────────────────────────────
   Smart Cart Management System – Frontend JavaScript
   Connects to Flask backend via REST API + Socket.IO WebSocket
   ────────────────────────────────────────────────────────────── */

const API_BASE = window.location.origin; // same origin as Flask

// ── Socket.IO ──────────────────────────────────────────────────
let socket = null;

function initSocket() {
  socket = io(API_BASE, { transports: ["websocket", "polling"] });

  socket.on("connect", () => {
    setWsStatus(true);
    showToast("Connected to server", "success");
  });

  socket.on("disconnect", () => {
    setWsStatus(false);
  });

  socket.on("cart_update", (data) => {
    addFeedItem(data);
    updateDashboardStats();

    // Refresh the monitored cart if it matches
    const monId = document.getElementById("monitorCartId").value.trim();
    if (monId && monId === data.cart_id) {
      loadCartMonitor(monId);
    }
  });

  socket.on("checkout", (data) => {
    addFeedItem({ ...data, product_name: "CHECKOUT", fraud_detected: false });
    updateDashboardStats();
    loadSessions();
  });
}

function setWsStatus(connected) {
  const el = document.getElementById("wsStatus");
  el.textContent = connected ? "🟢 Connected" : "⚫ Disconnected";
  el.className = "connection-status " + (connected ? "connected" : "disconnected");
}

// ── Navigation ─────────────────────────────────────────────────
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("page-" + btn.dataset.page).classList.add("active");

    // Load data when switching pages
    if (btn.dataset.page === "dashboard") updateDashboardStats();
    if (btn.dataset.page === "catalog")   loadProducts();
    if (btn.dataset.page === "carts")     loadSessions();
    if (btn.dataset.page === "fraud")     loadFraudLogs();
  });
});

// ── Dashboard Stats ────────────────────────────────────────────
async function updateDashboardStats() {
  try {
    const data = await apiFetch("/api/stats");
    document.getElementById("val-active-carts").textContent = data.active_carts;
    document.getElementById("val-products").textContent      = data.total_products;
    document.getElementById("val-fraud").textContent         = data.fraud_today;
    document.getElementById("val-revenue").textContent       = "PKR " + data.revenue_today.toFixed(2);
  } catch (e) {
    console.error("Stats fetch failed", e);
  }
}

// ── Cart Monitor ───────────────────────────────────────────────
function subscribeCart() {
  const cartId = document.getElementById("monitorCartId").value.trim();
  if (!cartId) { showToast("Enter a Cart ID", "warn"); return; }
  if (socket) socket.emit("subscribe_cart", { cart_id: cartId });
  loadCartMonitor(cartId);
}

async function loadCartMonitor(cartId) {
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(cartId)}`);
    const infoEl = document.getElementById("cartInfo");
    infoEl.innerHTML = `
      <div class="meta">
        <span>Cart: <strong>${data.session.cart_id}</strong></span>
        <span>Items: <strong>${data.item_count}</strong></span>
        <span>Status: <strong>${data.session.status}</strong></span>
      </div>
      <div class="total">Total: PKR ${(data.total || 0).toFixed(2)}</div>`;

    const listEl = document.getElementById("cartItemsList");
    if (!data.items.length) {
      listEl.innerHTML = '<div class="empty-state" style="padding:8px 0">No items yet</div>';
      return;
    }
    listEl.innerHTML = data.items.map((item) => `
      <div class="cart-item-row ${item.fraud_detected ? "fraud" : ""}">
        <span>${item.product_name}</span>
        <span>${item.actual_weight.toFixed(0)}g</span>
        <span>PKR ${item.price.toFixed(2)}</span>
        ${item.fraud_detected ? '<span class="fraud-badge">FRAUD</span>' : ""}
      </div>`).join("");
  } catch (e) {
    document.getElementById("cartInfo").innerHTML =
      `<div class="empty-state">No active session for this cart</div>`;
    document.getElementById("cartItemsList").innerHTML = "";
  }
}

// ── Activity Feed ──────────────────────────────────────────────
function addFeedItem(data) {
  const feed = document.getElementById("activityFeed");
  const empty = feed.querySelector(".empty-state");
  if (empty) empty.remove();

  const li = document.createElement("li");
  const now = new Date().toLocaleTimeString();
  li.innerHTML = `
    <span class="feed-time">${now}</span>
    <span class="feed-body">
      <strong>${data.product_name || "Event"}</strong>
      ${data.fraud_detected
        ? `<span class="fraud-tag">⚠ FRAUD – ${data.alert_message || ""}</span>`
        : `<span>Cart: ${data.cart_id} | PKR ${(data.price || 0).toFixed(2)}</span>`}
    </span>`;
  feed.prepend(li);

  // Keep last 50 items
  while (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

function clearFeed() {
  document.getElementById("activityFeed").innerHTML =
    '<li class="empty-state">Waiting for activity…</li>';
}

// ── Products ───────────────────────────────────────────────────
let allProducts = [];

async function loadProducts() {
  allProducts = await apiFetch("/api/products");
  renderProducts(allProducts);
}

function renderProducts(products) {
  const tbody = document.getElementById("productsBody");
  if (!products.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No products found</td></tr>';
    return;
  }
  tbody.innerHTML = products.map((p) => `
    <tr>
      <td>${p.id}</td>
      <td><code>${p.rfid_uid}</code></td>
      <td>${p.name}</td>
      <td>${p.category || "—"}</td>
      <td>PKR ${p.price.toFixed(2)}</td>
      <td>${p.expected_weight.toFixed(1)}</td>
      <td>
        <button class="btn btn-sm" onclick="openEditProduct(${p.id})">Edit</button>
        <button class="btn btn-sm btn-danger" onclick="deleteProduct(${p.id})">Delete</button>
      </td>
    </tr>`).join("");
}

function filterProducts() {
  const q = document.getElementById("searchProducts").value.toLowerCase();
  renderProducts(allProducts.filter((p) =>
    p.name.toLowerCase().includes(q) ||
    p.rfid_uid.toLowerCase().includes(q) ||
    (p.category || "").toLowerCase().includes(q)
  ));
}

function openAddProduct() {
  document.getElementById("modalTitle").textContent = "Add Product";
  document.getElementById("productForm").reset();
  document.getElementById("editProductId").value = "";
  document.getElementById("fRfidUid").disabled = false;
  document.getElementById("productModal").classList.add("open");
}

async function openEditProduct(id) {
  const p = allProducts.find((x) => x.id === id);
  if (!p) return;
  document.getElementById("modalTitle").textContent = "Edit Product";
  document.getElementById("editProductId").value  = id;
  document.getElementById("fRfidUid").value       = p.rfid_uid;
  document.getElementById("fRfidUid").disabled    = true; // UID is the key
  document.getElementById("fName").value          = p.name;
  document.getElementById("fCategory").value      = p.category || "";
  document.getElementById("fPrice").value         = p.price;
  document.getElementById("fWeight").value        = p.expected_weight;
  document.getElementById("productModal").classList.add("open");
}

function closeProductModal() {
  document.getElementById("productModal").classList.remove("open");
}

async function saveProduct(e) {
  e.preventDefault();
  const id = document.getElementById("editProductId").value;
  const payload = {
    rfid_uid:        document.getElementById("fRfidUid").value.trim().toUpperCase(),
    name:            document.getElementById("fName").value.trim(),
    category:        document.getElementById("fCategory").value.trim(),
    price:           parseFloat(document.getElementById("fPrice").value),
    expected_weight: parseFloat(document.getElementById("fWeight").value),
  };
  try {
    if (id) {
      await apiFetch(`/api/products/${id}`, { method: "PUT", body: JSON.stringify(payload) });
      showToast("Product updated", "success");
    } else {
      await apiFetch("/api/products", { method: "POST", body: JSON.stringify(payload) });
      showToast("Product added", "success");
    }
    closeProductModal();
    loadProducts();
    updateDashboardStats();
  } catch (err) {
    showToast(err.message || "Save failed", "error");
  }
}

async function deleteProduct(id) {
  if (!confirm("Delete this product?")) return;
  try {
    await apiFetch(`/api/products/${id}`, { method: "DELETE" });
    showToast("Product deleted", "success");
    loadProducts();
    updateDashboardStats();
  } catch (err) {
    showToast(err.message || "Delete failed", "error");
  }
}

// ── Sessions ───────────────────────────────────────────────────
let currentSessionCartId = null;

async function loadSessions() {
  const sessions = await apiFetch("/api/carts");
  const tbody = document.getElementById("sessionsBody");
  if (!sessions.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No sessions yet</td></tr>';
    return;
  }
  tbody.innerHTML = sessions.map((s) => `
    <tr>
      <td>${s.id}</td>
      <td><strong>${s.cart_id}</strong></td>
      <td><span class="badge badge-${s.status}">${s.status}</span></td>
      <td>PKR ${(s.total || 0).toFixed(2)}</td>
      <td>${fmtDate(s.started_at)}</td>
      <td>${s.ended_at ? fmtDate(s.ended_at) : "—"}</td>
      <td>
        ${s.status === "active"
          ? `<button class="btn btn-sm btn-primary" onclick="viewSession('${s.cart_id}')">View</button>`
          : "—"}
      </td>
    </tr>`).join("");
}

async function viewSession(cartId) {
  currentSessionCartId = cartId;
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(cartId)}`);
    document.getElementById("sessionModalCartId").textContent = cartId;
    document.getElementById("sessionDetail").innerHTML = `
      <p>Items: <strong>${data.item_count}</strong> &nbsp;|&nbsp; Total: <strong>PKR ${(data.total || 0).toFixed(2)}</strong></p>
      <div class="table-wrap" style="margin-top:12px">
        <table>
          <thead>
            <tr><th>Product</th><th>Expected (g)</th><th>Actual (g)</th><th>Price</th><th>Fraud</th></tr>
          </thead>
          <tbody>
            ${data.items.map((i) => `
              <tr>
                <td>${i.product_name}</td>
                <td>${i.expected_weight.toFixed(1)}</td>
                <td>${i.actual_weight.toFixed(1)}</td>
                <td>PKR ${i.price.toFixed(2)}</td>
                <td>${i.fraud_detected ? '<span class="badge" style="background:#fee2e2;color:#b91c1c">FRAUD</span>' : "✅"}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`;
    document.getElementById("sessionModal").classList.add("open");
  } catch (e) {
    showToast("Could not load session", "error");
  }
}

function closeSessionModal() {
  document.getElementById("sessionModal").classList.remove("open");
  currentSessionCartId = null;
}

async function checkoutCart() {
  if (!currentSessionCartId) return;
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(currentSessionCartId)}/checkout`, { method: "POST" });
    showToast(`Checkout complete – PKR ${data.total.toFixed(2)}`, "success");
    closeSessionModal();
    loadSessions();
    updateDashboardStats();
  } catch (e) {
    showToast("Checkout failed", "error");
  }
}

// ── Fraud Logs ─────────────────────────────────────────────────
async function loadFraudLogs() {
  const logs = await apiFetch("/api/fraud-logs");
  const tbody = document.getElementById("fraudBody");
  if (!logs.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--muted)">No fraud events recorded</td></tr>';
    return;
  }
  tbody.innerHTML = logs.map((l) => `
    <tr>
      <td>${l.id}</td>
      <td>${l.cart_id}</td>
      <td>${l.product_name}</td>
      <td>${l.expected_weight.toFixed(1)}</td>
      <td>${l.actual_weight.toFixed(1)}</td>
      <td style="color:var(--danger);font-weight:600">${l.deviation_pct.toFixed(1)}%</td>
      <td>${fmtDate(l.flagged_at)}</td>
    </tr>`).join("");
}

// ── Admin ──────────────────────────────────────────────────────
async function simulateScan() {
  const cartId = document.getElementById("simCartId").value.trim();
  const uid    = document.getElementById("simRfidUid").value.trim().toUpperCase();
  const weight = parseFloat(document.getElementById("simWeight").value);
  if (!cartId || !uid || isNaN(weight)) {
    showToast("Fill all simulation fields", "warn"); return;
  }
  try {
    const result = await apiFetch("/api/scan", {
      method: "POST",
      body: JSON.stringify({ cart_id: cartId, rfid_uid: uid, actual_weight: weight }),
    });
    document.getElementById("simResult").textContent = JSON.stringify(result, null, 2);
  } catch (e) {
    document.getElementById("simResult").textContent = "Error: " + (e.message || e);
  }
}

async function adminCheckout() {
  const cartId = document.getElementById("adminCartId").value.trim();
  if (!cartId) { showToast("Enter a Cart ID", "warn"); return; }
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(cartId)}/checkout`, { method: "POST" });
    document.getElementById("adminResult").textContent = JSON.stringify(data, null, 2);
    showToast("Checkout done", "success");
    loadSessions();
  } catch (e) {
    document.getElementById("adminResult").textContent = "Error: " + (e.message || e);
  }
}

async function adminClearCart() {
  const cartId = document.getElementById("adminCartId").value.trim();
  if (!cartId) { showToast("Enter a Cart ID", "warn"); return; }
  if (!confirm(`Clear cart ${cartId}?`)) return;
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(cartId)}/clear`, { method: "POST" });
    document.getElementById("adminResult").textContent = JSON.stringify(data, null, 2);
    showToast("Cart cleared", "success");
    loadSessions();
  } catch (e) {
    document.getElementById("adminResult").textContent = "Error: " + (e.message || e);
  }
}

async function adminViewCart() {
  const cartId = document.getElementById("adminCartId").value.trim();
  if (!cartId) { showToast("Enter a Cart ID", "warn"); return; }
  try {
    const data = await apiFetch(`/api/carts/${encodeURIComponent(cartId)}`);
    document.getElementById("adminResult").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    document.getElementById("adminResult").textContent = "Error: " + (e.message || e);
  }
}

// ── Utilities ──────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const resp = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const json = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(json.error || `HTTP ${resp.status}`);
  return json;
}

function showToast(msg, type = "") {
  const t = document.getElementById("toast");
  t.textContent  = msg;
  t.className    = "toast show" + (type ? " " + type : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.className = "toast"; }, 3000);
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

// ── Init ───────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initSocket();
  updateDashboardStats();
  loadProducts();    // preload for catalog
});
