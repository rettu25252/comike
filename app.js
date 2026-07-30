const STORAGE_KEY = "shopping-list-app-v1";

const defaultState = {
  password: null,
  adminPassword: null,
  editableListIds: [],
  undoState: null,
  serverVersion: 0,
  history: {
    undo: [],
    redo: []
  },
  filters: {
    location: "all",
    showOnlyTodo: false,
    sortBy: "position"
  },
  lists: [],
  currentListId: null,
  view: "password"
};

const PURCHASE_STATUSES = ["done", "todo", "partial"];

// sessionRole lives outside state so state replacements never reset it
let sessionRole = null;
let state = loadStateFromLocal();
let syncInFlight = false;

const PRIORITY_OPTIONS = [
  { value: "", label: "未設定" },
  { value: "第一優先", label: "第一優先" },
  { value: "第二優先", label: "第二優先" },
  { value: "第三優先", label: "第三優先" },
  { value: "第四優先", label: "第四優先" },
  { value: "第五優先", label: "第五優先" }
];

function normalizeState(rawState) {
  const source = rawState || {};
  const normalizedLists = Array.isArray(source.lists) && source.lists.length
    ? source.lists.map((list) => ({
        ...list,
        locations: Array.isArray(list.locations) ? list.locations : [],
        items: Array.isArray(list.items) ? list.items.map((item) => normalizeItem(item)) : []
      }))
    : structuredClone(defaultState.lists);

  return {
    ...structuredClone(defaultState),
    ...source,
    sessionRole: undefined,
    serverVersion: Number(source.serverVersion || 0),
    undoState: source.undoState || null,
    history: {
      undo: Array.isArray(source.history?.undo) ? source.history.undo : [],
      redo: Array.isArray(source.history?.redo) ? source.history.redo : []
    },
    filters: {
      ...structuredClone(defaultState.filters),
      ...(source.filters || {})
    },
    editableListIds: Array.isArray(source.editableListIds) ? source.editableListIds : [],
    lists: normalizedLists
  };
}

function normalizeItem(item) {
  if (!item) {
    return { id: `item-${Date.now()}`, name: "", price: "", memo: "", purchaseStatus: "todo", purchased: false, location: "", position: "", priority: "" };
  }

  if (item.purchaseStatus && PURCHASE_STATUSES.includes(item.purchaseStatus)) {
    return {
      ...item,
      purchased: item.purchaseStatus === "done",
      location: item.location || "",
      position: item.position || "",
      priority: item.priority || ""
    };
  }

  return {
    ...item,
    purchaseStatus: item.purchased ? "done" : "todo",
    purchased: Boolean(item.purchased),
    location: item.location || "",
    position: item.position || "",
    priority: item.priority || ""
  };
}

function getPriorityRank(priority) {
  const rank = PRIORITY_OPTIONS.findIndex((option) => option.value === priority);
  return rank > 0 ? rank : 999;
}

function getPriorityClass(priority) {
  switch (priority) {
    case "第一優先":
      return "priority-first";
    case "第二優先":
      return "priority-second";
    case "第三優先":
      return "priority-third";
    case "第四優先":
      return "priority-fourth";
    case "第五優先":
      return "priority-fifth";
    default:
      return "";
  }
}

function getItemPurchaseStatus(item) {
  return item?.purchaseStatus || "todo";
}

function getNextPurchaseStatus(status) {
  const statusOrder = ["todo", "done", "partial"];
  const currentIndex = statusOrder.indexOf(status);
  return statusOrder[(currentIndex + 1) % statusOrder.length];
}

function applyPurchaseStatus(item, status, listId = null) {
  const previousStatus = getItemPurchaseStatus(item);
  const previousPurchased = Boolean(item.purchased);
  const changed = previousStatus !== status || previousPurchased !== (status === "done");
  if (changed) {
    const historyEntry = {
      listId: listId || state.currentListId,
      itemId: item.id,
      previousStatus,
      previousPurchased,
      nextStatus: status,
      nextPurchased: status === "done"
    };

    state.history.undo.push(historyEntry);
    if (state.history.undo.length > 50) {
      state.history.undo.shift();
    }
    state.history.redo = [];
    state.undoState = historyEntry;
  }

  item.purchaseStatus = status;
  item.purchased = status === "done";
  saveState();
  render();
}

function restoreHistoryEntry(entry, target) {
  const list = state.lists.find((candidate) => candidate.id === entry.listId);
  if (!list) {
    return false;
  }

  const item = list.items.find((candidate) => candidate.id === entry.itemId);
  if (!item) {
    return false;
  }

  if (target === "previous") {
    item.purchaseStatus = entry.previousStatus;
    item.purchased = Boolean(entry.previousPurchased);
  } else {
    item.purchaseStatus = entry.nextStatus;
    item.purchased = Boolean(entry.nextPurchased);
  }

  return true;
}

function undoLastPurchaseChange() {
  const historyEntry = state.history.undo.pop();
  if (!historyEntry) {
    return;
  }

  if (!restoreHistoryEntry(historyEntry, "previous")) {
    state.history.undo.push(historyEntry);
    return;
  }

  state.history.redo.push(historyEntry);
  state.undoState = historyEntry;
  saveState();
  render();
}

function redoLastPurchaseChange() {
  const historyEntry = state.history.redo.pop();
  if (!historyEntry) {
    return;
  }

  if (!restoreHistoryEntry(historyEntry, "next")) {
    state.history.redo.push(historyEntry);
    return;
  }

  state.history.undo.push(historyEntry);
  state.undoState = historyEntry;
  saveState();
  render();
}

function clearStatusHold(button) {
  if (!button) return;
  const timerId = Number(button.dataset.longPressTimer || "0");
  if (timerId) {
    window.clearTimeout(timerId);
  }
  delete button.dataset.longPressTimer;
}

function startStatusHold(button, itemId) {
  if (!button || !itemId) return;
  clearStatusHold(button);
  button.dataset.longPressTriggered = "false";
  const timerId = window.setTimeout(() => {
    const list = getCurrentList();
    const item = list?.items.find((entry) => entry.id === itemId);
    if (!item) return;
    button.dataset.longPressTriggered = "true";
    applyPurchaseStatus(item, "partial", list?.id);
  }, 2000);
  button.dataset.longPressTimer = String(timerId);
}

function getPurchaseLabel(status) {
  return {
    todo: "未購入",
    partial: "一部購入済み",
    done: "購入済み"
  }[status] || "未購入";
}

function getPurchaseClass(status) {
  return status || "todo";
}

function getApiBaseUrl() {
  const origin = window.location.origin;
  if (origin && origin !== "null") {
    return origin;
  }
  return "http://127.0.0.1:8000";
}

function buildApiUrl(path) {
  return `${getApiBaseUrl()}${path}`;
}

function loadStateFromLocal() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    if (!value) {
      return normalizeState(structuredClone(defaultState));
    }

    return normalizeState(JSON.parse(value));
  } catch (error) {
    console.warn("Failed to load state", error);
    return normalizeState(structuredClone(defaultState));
  }
}

function saveStateToLocal() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

async function loadStateFromServer() {
  // view/currentListId/filters are also client-only; preserve them too
  const currentView = state.view;
  const currentListId = state.currentListId;
  const currentFilters = state.filters;
  try {
    const response = await fetch(buildApiUrl("/api/state"));
    if (!response.ok) {
      throw new Error(`Failed to load server state: ${response.status}`);
    }

    const payload = await response.json();
    if (payload?.state) {
      state = normalizeState(payload.state);
      state.view = currentView;
      state.currentListId = currentListId;
      state.filters = currentFilters;
      state.serverVersion = Number(payload.version || 0);
      saveStateToLocal();
      return true;
    }
  } catch (error) {
    console.warn("Failed to load server state", error);
  }

  return false;
}

async function syncStateToServer() {
  if (syncInFlight) {
    return;
  }

  syncInFlight = true;
  try {
    const response = await fetch(buildApiUrl("/api/state"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: { ...state, sessionRole: undefined, view: null, currentListId: null, filters: null }, version: state.serverVersion || 0 })
    });

    if (!response.ok) {
      if (response.status === 409) {
        const payload = await response.json();
        if (payload?.state) {
          const savedView = state.view;
          const savedListId = state.currentListId;
          const savedFilters = state.filters;
          state = normalizeState(payload.state);
          state.view = savedView;
          state.currentListId = savedListId;
          state.filters = savedFilters;
          state.serverVersion = Number(payload.version || 0);
          saveStateToLocal();
          render();
        }
        alert("他のユーザーの更新が反映されました。最新データを読み込み直しました。");
        return;
      }
      throw new Error(`Failed to save server state: ${response.status}`);
    }

    const payload = await response.json();
    state.serverVersion = Number(payload.version || 0);
    saveStateToLocal();
  } catch (error) {
    console.warn("Failed to sync state to server", error);
  } finally {
    syncInFlight = false;
  }
}

function saveState() {
  saveStateToLocal();
  void syncStateToServer();
}

function canCreateLists() {
  return sessionRole === "owner";
}

function canEditList(list) {
  if (!list) {
    return false;
  }

  return sessionRole === "owner" || (Array.isArray(state.editableListIds) && state.editableListIds.includes(list.id));
}

function grantEditAccess(listId) {
  if (!listId) {
    return;
  }

  if (!Array.isArray(state.editableListIds)) {
    state.editableListIds = [];
  }

  if (!state.editableListIds.includes(listId)) {
    state.editableListIds.push(listId);
  }
}

function requireEditAccess(list, message = "閲覧モードのため、編集はできません。") {
  if (!canEditList(list)) {
    alert(message);
    return false;
  }

  return true;
}

function getCurrentList() {
  return state.lists.find((list) => list.id === state.currentListId) || null;
}

function getRouteFromHash() {
  const hash = (window.location.hash || "").replace(/^#/, "");
  const segments = hash.split("/").filter(Boolean);

  if (!segments.length) {
    return { view: "lists", listId: null };
  }

  if (segments[0] === "password") {
    return { view: "password", listId: null };
  }

  if (segments[0] !== "lists") {
    return { view: "lists", listId: null };
  }

  if (segments[1] && segments[2] === "edit") {
    return { view: "edit", listId: segments[1] };
  }

  if (segments[1]) {
    return { view: "list", listId: segments[1] };
  }

  return { view: "lists", listId: null };
}

function buildHashFromState() {
  if (state.view === "password") {
    return "password";
  }

  if (state.view === "lists") {
    return "lists";
  }

  const currentList = getCurrentList();
  if (!currentList) {
    return "lists";
  }

  if (state.view === "edit") {
    return `lists/${currentList.id}/edit`;
  }

  return `lists/${currentList.id}`;
}

function applyRoute(route) {
  if (route.view === "password") {
    state.view = "password";
    state.currentListId = null;
    return;
  }

  if (route.view === "lists") {
    state.view = "lists";
    state.currentListId = null;
    return;
  }

  if (route.listId) {
    const targetList = state.lists.find((list) => list.id === route.listId);
    if (targetList) {
      state.currentListId = route.listId;
      state.view = route.view;
      return;
    }
  }

  state.view = "lists";
  state.currentListId = null;
}

function updateUrl(replace = false) {
  const hash = buildHashFromState();
  const target = `#${hash}`;

  if (window.location.hash === target) {
    return;
  }

  if (replace) {
    history.replaceState({ route: hash }, "", target);
  } else {
    history.pushState({ route: hash }, "", target);
  }
}

function handleHashChange() {
  applyRoute(getRouteFromHash());
  render();
}

function showView(viewName) {
  state.view = viewName;
  if (viewName === "password" || viewName === "lists") {
    state.currentListId = null;
  }

  const viewIdMap = {
    password: "passwordView",
    lists: "listsView",
    list: "viewListView",
    edit: "editListView"
  };

  const targetViewId = viewIdMap[viewName] || "passwordView";
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === targetViewId));
  const logoutButton = document.getElementById("logoutBtn");
  if (logoutButton) {
    logoutButton.style.display = viewName === "password" ? "none" : "inline-block";
  }
}

function navigateTo(viewName, listId = null, options = {}) {
  state.view = viewName;

  if (listId) {
    state.currentListId = listId;
  } else if (viewName === "password" || viewName === "lists") {
    state.currentListId = null;
  }

  if ((viewName === "list" || viewName === "edit") && (!state.currentListId || !getCurrentList())) {
    state.view = "lists";
    state.currentListId = null;
  }

  saveState();
  if (options.updateUrl !== false) {
    updateUrl(options.replace);
  }
  render();
}

function updateHeader() {
  const title = document.getElementById("pageTitle");
  const subtitle = document.getElementById("pageSubtitle");

  if (state.view === "password") {
    title.textContent = "買い物リスト";
    subtitle.textContent = "誰でも閲覧・編集できる公開リストです。";
    return;
  }

  const currentList = getCurrentList();
  title.textContent = currentList ? currentList.name : "買い物リスト";
  subtitle.textContent = currentList ? "アイテムを確認して、購入状態を更新できます。" : "リストを選んでください。";
}

function renderPasswordView() {
  // tab UI is managed by setPasswordTab; nothing dynamic needed here
}

function renderListsView() {
  const container = document.getElementById("listsContainer");
  const createButton = document.getElementById("createListBtn");
  const changePwBtn = document.getElementById("changePwBtn");
  const deleteRoomBtn = document.getElementById("deleteRoomBtn");
  container.innerHTML = "";

  const isOwner = sessionRole === "owner";
  if (createButton) {
    createButton.style.display = canCreateLists() ? "inline-block" : "none";
  }
  if (changePwBtn) {
    changePwBtn.style.display = isOwner ? "inline-block" : "none";
  }
  if (deleteRoomBtn) {
    deleteRoomBtn.style.display = isOwner ? "inline-block" : "none";
  }

  if (!state.lists.length) {
    container.innerHTML = '<p class="hint-text">まだリストがありません。</p>';
    return;
  }

  state.lists.forEach((list) => {
    const card = document.createElement("article");
    card.className = "list-card";
    card.dataset.listId = list.id;
    card.innerHTML = `
      <h3>${escapeHtml(list.name)}</h3>
      <p class="hint-text">${escapeHtml(String(list.items.length))}件のアイテム</p>
    `;
    container.appendChild(card);
  });
}

function renderListView() {
  const title = document.getElementById("currentListTitle");
  const list = getCurrentList();
  const itemsList = document.getElementById("itemsList");
  const locationFilter = document.getElementById("locationFilterSelect");
  const onlyTodoCheckbox = document.getElementById("onlyTodoCheckbox");
  const sortSelect = document.getElementById("sortSelect");
  const createButton = document.getElementById("createListFromViewBtn");
  const editButton = document.getElementById("editListBtn");
  const accessBadge = document.getElementById("accessBadge");

  if (!list) {
    title.textContent = "リストが選択されていません";
    itemsList.innerHTML = "";
    return;
  }

  title.textContent = list.name;
  const canEdit = canEditList(list);
  if (accessBadge) {
    accessBadge.textContent = canEdit ? "編集可能" : "閲覧のみ";
    accessBadge.classList.toggle("viewer", !canEdit);
  }
  if (createButton) {
    createButton.style.display = canEdit ? "inline-block" : "none";
  }
  if (editButton) {
    editButton.style.display = canEdit ? "inline-block" : "none";
  }
  locationFilter.innerHTML = '<option value="all">すべて</option>' + (list.locations || []).map((location) => `<option value="${escapeHtml(location)}">${escapeHtml(location)}</option>`).join("");
  locationFilter.value = state.filters.location || "all";
  onlyTodoCheckbox.checked = Boolean(state.filters.showOnlyTodo);
  sortSelect.value = state.filters.sortBy || "position";
  itemsList.innerHTML = "";

  const filteredItems = list.items.filter((item) => {
    const matchesLocation = !state.filters.location || state.filters.location === "all" || item.location === state.filters.location;
    const matchesTodo = !state.filters.showOnlyTodo || getItemPurchaseStatus(item) === "todo";
    return matchesLocation && matchesTodo;
  });

  const sortedItems = [...filteredItems].sort((a, b) => {
    if (state.filters.sortBy === "name") {
      return (a.name || "").localeCompare(b.name || "", "ja", { sensitivity: "base" });
    }
    if (state.filters.sortBy === "priority") {
      return getPriorityRank(a.priority) - getPriorityRank(b.priority);
    }
    return (a.position || "").localeCompare(b.position || "", "ja", { sensitivity: "base" });
  });

  if (!sortedItems.length) {
    itemsList.innerHTML = '<li class="hint-text">条件に一致するアイテムがありません。</li>';
    return;
  }

  sortedItems.forEach((item) => {
    const row = document.createElement("li");
    const status = getItemPurchaseStatus(item);
    row.className = `item-row ${status === "done" ? "purchased" : ""} ${getPriorityClass(item.priority)}`.trim();
    row.innerHTML = `
      <div class="status-row">
        <strong>${escapeHtml(item.name)}</strong>
        <button type="button" class="status-toggle ${getPurchaseClass(status)}" data-action="toggle-status" data-item-id="${escapeHtml(item.id)}">${getPurchaseLabel(status)}</button>
      </div>
      <div class="meta">場所: ${escapeHtml(item.location || "未設定")}</div>
      <div class="meta">位置: ${escapeHtml(item.position || "未設定")}</div>
      <div class="meta">価格: ${escapeHtml(item.price || "未設定")}</div>
      <div class="meta">メモ: ${escapeHtml(item.memo || "なし")}</div>
    `;
    itemsList.appendChild(row);
  });
}

function renderEditView() {
  const list = getCurrentList();
  const listNameInput = document.getElementById("listNameInput");
  const container = document.getElementById("editItemsContainer");
  const locationTags = document.getElementById("locationTags");

  if (!list) {
    listNameInput.value = "";
    container.innerHTML = "";
    locationTags.innerHTML = "";
    return;
  }

  if (!canEditList(list)) {
    listNameInput.value = list.name;
    container.innerHTML = '<p class="hint-text">閲覧モードのため、このリストは編集できません。</p>';
    locationTags.innerHTML = "";
    return;
  }

  listNameInput.value = list.name;
  locationTags.innerHTML = (list.locations || []).map((location) => `<button class="tag-pill" type="button" data-action="remove-location">${escapeHtml(location)}</button>`).join("");
  container.innerHTML = "";

  if (!list.items.length) {
    container.innerHTML = '<p class="hint-text">まだアイテムがありません。</p>';
    return;
  }

  list.items.forEach((item) => {
    const card = document.createElement("div");
    const status = getItemPurchaseStatus(item);
    card.className = "edit-item";
    card.innerHTML = `
      <div class="edit-item-header">
        <strong>${item.name}</strong>
        <button class="delete-button" type="button" data-action="delete-item" data-item-id="${item.id}">削除</button>
      </div>
      <label>品物名<input type="text" value="${escapeHtml(item.name)}" data-item-id="${item.id}" data-field="name" /></label>
      <label>価格<input type="text" value="${escapeHtml(item.price)}" data-item-id="${item.id}" data-field="price" /></label>
      <label>メモ<textarea rows="2" data-item-id="${item.id}" data-field="memo">${escapeHtml(item.memo || "")}</textarea></label>
      <label>場所<select data-item-id="${item.id}" data-field="location">${(list.locations || []).map((location) => `<option value="${escapeHtml(location)}" ${item.location === location ? "selected" : ""}>${escapeHtml(location)}</option>`).join("")}<option value="" ${!item.location ? "selected" : ""}>未設定</option></select></label>
      <label>位置<input type="text" value="${escapeHtml(item.position || "")}" maxlength="20" data-item-id="${item.id}" data-field="position" placeholder="未設定" /></label>
      <label>優先順位<select data-item-id="${item.id}" data-field="priority">${PRIORITY_OPTIONS.map((option) => `<option value="${escapeHtml(option.value)}" ${item.priority === option.value ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>
      <button type="button" class="status-toggle ${getPurchaseClass(status)}" data-action="toggle-status" data-item-id="${item.id}">${getPurchaseLabel(status)}</button>
    `;
    container.appendChild(card);
  });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function updateUndoButton() {
  const undoButton = document.getElementById("undoPurchaseBtn");
  const redoButton = document.getElementById("redoPurchaseBtn");
  const shouldShow = state.view === "list" || state.view === "edit";

  if (undoButton) {
    undoButton.disabled = state.history.undo.length === 0;
    undoButton.style.display = shouldShow ? "inline-block" : "none";
  }

  if (redoButton) {
    redoButton.disabled = state.history.redo.length === 0;
    redoButton.style.display = shouldShow ? "inline-block" : "none";
  }
}

function render() {
  // force password screen when not authenticated
  if (!sessionRole) {
    state.view = "password";
  }
  updateHeader();
  renderPasswordView();
  renderListsView();
  renderListView();
  renderEditView();
  updateUndoButton();
  showView(state.view);
}

function createList(name) {
  if (!canCreateLists()) {
    alert("閲覧モードのため、新規作成はできません。" );
    return;
  }

  const list = {
    id: `list-${Date.now()}`,
    name,
    items: []
  };
  state.lists.unshift(list);
  grantEditAccess(list.id);
  saveState();
  navigateTo("edit", list.id);
}

function updateItemField(itemId, field, value) {
  const list = getCurrentList();
  if (!list) return;
  if (!requireEditAccess(list, "閲覧モードのため、編集はできません。")) return;
  const item = list.items.find((entry) => entry.id === itemId);
  if (!item) return;
  item[field] = field === "purchased" ? value === "true" || value === true || value === "on" : value;
  saveState();
  render();
}

function deleteItem(itemId) {
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、削除はできません。")) return;
  list.items = list.items.filter((item) => item.id !== itemId);
  saveState();
  render();
}

function addItem(name, price, memo, location = "", position = "", priority = "") {
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、新規追加はできません。")) return;
  list.items.push({
    id: `item-${Date.now()}`,
    name,
    price,
    memo,
    purchaseStatus: "todo",
    purchased: false,
    location,
    position,
    priority
  });
  saveState();
  render();
}

function setPasswordTab(tab) {
  document.getElementById("createRoomPanel").style.display = tab === "create" ? "block" : "none";
  document.getElementById("enterRoomPanel").style.display = tab === "enter" ? "block" : "none";
  document.getElementById("tabCreateRoom").classList.toggle("active", tab === "create");
  document.getElementById("tabEnterRoom").classList.toggle("active", tab === "enter");
}

document.getElementById("tabCreateRoom").addEventListener("click", () => setPasswordTab("create"));
document.getElementById("tabEnterRoom").addEventListener("click", () => setPasswordTab("enter"));

document.getElementById("createRoomForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const roomPw = document.getElementById("createPwInput").value;
  const adminPw = document.getElementById("createAdminPwInput").value;
  if (!roomPw || !adminPw) {
    alert("部屋のPWと管理者PWの両方を入力してください。");
    return;
  }
  // if room exists and admin PW matches, log in as admin without resetting
  if (state.adminPassword && adminPw === state.adminPassword) {
    sessionRole = "owner";
    saveState();
    navigateTo("lists");
    return;
  }
  // create new room (or re-create if admin PW didn't match an existing room)
  if (state.adminPassword && adminPw !== state.adminPassword) {
    alert("管理者PWが違います。");
    return;
  }
  state.password = roomPw;
  state.adminPassword = adminPw;
  sessionRole = "owner";
  saveState();
  navigateTo("lists");
});

document.getElementById("enterRoomForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const pw = document.getElementById("enterPwInput").value;
  if (!state.password) {
    alert("まだ部屋が作られていません。「部屋を作る」から部屋を作成してください。");
    return;
  }
  if (pw === state.password) {
    sessionRole = "viewer";
    saveState();
    navigateTo("lists");
  } else {
    alert("パスワードが違います。");
  }
});

function handleLogout() {
  navigateTo("password");
}

const logoutButton = document.getElementById("logoutBtn");
if (logoutButton) {
  logoutButton.addEventListener("click", handleLogout);
}

function openCreateListModal() {
  if (!canCreateLists()) {
    alert("閲覧モードのため、新規作成はできません。" );
    return;
  }

  const modal = document.getElementById("createListModal");
  const input = document.getElementById("newListNameInput");
  modal.classList.remove("hidden");
  input.value = "";
  input.focus();
}

function closeCreateListModal() {
  document.getElementById("createListModal").classList.add("hidden");
}

function populateNewItemLocationOptions() {
  const select = document.getElementById("newItemLocationInput");
  const list = getCurrentList();
  if (!select) return;

  const locations = list?.locations || [];
  select.innerHTML = '<option value="">未設定</option>' + locations.map((location) => `<option value="${escapeHtml(location)}">${escapeHtml(location)}</option>`).join("");
}

function openCreateItemModal() {
  const list = getCurrentList();
  if (!canEditList(list)) {
    alert("閲覧モードのため、新規追加はできません。" );
    return;
  }

  const modal = document.getElementById("createItemModal");
  const input = document.getElementById("newItemNameInput");
  modal.classList.remove("hidden");
  input.value = "";
  document.getElementById("newItemPriceInput").value = "";
  populateNewItemLocationOptions();
  document.getElementById("newItemLocationInput").value = "";
  document.getElementById("newItemPositionInput").value = "";
  document.getElementById("newItemMemoInput").value = "";
  input.focus();
}

function closeCreateItemModal() {
  document.getElementById("createItemModal").classList.add("hidden");
}

document.getElementById("createListBtn").addEventListener("click", () => {
  openCreateListModal();
});

document.getElementById("createListFromViewBtn").addEventListener("click", () => {
  openCreateItemModal();
});

document.getElementById("cancelCreateListBtn").addEventListener("click", () => {
  closeCreateListModal();
});

document.getElementById("confirmCreateListBtn").addEventListener("click", () => {
  const input = document.getElementById("newListNameInput");
  const name = input.value.trim();
  if (!name) return;
  createList(name);
  closeCreateListModal();
});

document.getElementById("newListNameInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("confirmCreateListBtn").click();
  }
});

document.getElementById("cancelCreateItemBtn").addEventListener("click", () => {
  closeCreateItemModal();
});

document.getElementById("confirmCreateItemBtn").addEventListener("click", () => {
  const nameInput = document.getElementById("newItemNameInput");
  const priceInput = document.getElementById("newItemPriceInput");
  const locationInput = document.getElementById("newItemLocationInput");
  const positionInput = document.getElementById("newItemPositionInput");
  const priorityInput = document.getElementById("newItemPriorityInput");
  const memoInput = document.getElementById("newItemMemoInput");
  const name = nameInput.value.trim();
  if (!name) return;

  addItem(
    name,
    priceInput.value.trim(),
    memoInput.value.trim(),
    locationInput.value.trim(),
    positionInput.value.trim(),
    priorityInput.value.trim()
  );
  closeCreateItemModal();
});

document.getElementById("newItemNameInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("confirmCreateItemBtn").click();
  }
});

document.getElementById("listsContainer").addEventListener("click", (event) => {
  const card = event.target.closest(".list-card");
  if (!card) return;
  navigateTo("list", card.dataset.listId);
});

document.getElementById("backToListsBtn").addEventListener("click", () => {
  navigateTo("lists");
});

document.getElementById("undoPurchaseBtn").addEventListener("click", () => {
  undoLastPurchaseChange();
});

document.getElementById("redoPurchaseBtn").addEventListener("click", () => {
  redoLastPurchaseChange();
});

document.getElementById("editListBtn").addEventListener("click", () => {
  const list = getCurrentList();
  if (!canEditList(list)) {
    alert("閲覧モードのため、編集はできません。" );
    return;
  }
  navigateTo("edit", state.currentListId);
});

document.getElementById("cancelEditBtn").addEventListener("click", () => {
  navigateTo("list", state.currentListId);
});

document.getElementById("saveListBtn").addEventListener("click", () => {
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、保存はできません。")) return;
  const nameInput = document.getElementById("listNameInput");
  list.name = nameInput.value.trim() || list.name;
  saveState();
  navigateTo("list", state.currentListId);
});

document.getElementById("editItemsContainer").addEventListener("input", (event) => {
  const target = event.target;
  const itemId = target.dataset.itemId;
  const field = target.dataset.field;
  if (!itemId || !field) return;
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、編集はできません。")) return;
  const item = list.items.find((entry) => entry.id === itemId);
  if (!item) return;

  item[field] = target.value;
  if (field === "location" && target.value && !list.locations.includes(target.value)) {
    list.locations.push(target.value);
  }
  saveState();
  render();
});

document.getElementById("editItemsContainer").addEventListener("mousedown", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  startStatusHold(target, target.dataset.itemId);
});

document.getElementById("editItemsContainer").addEventListener("mouseup", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
});

document.getElementById("editItemsContainer").addEventListener("mouseleave", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
});

document.getElementById("editItemsContainer").addEventListener("touchstart", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  startStatusHold(target, target.dataset.itemId);
}, { passive: true });

document.getElementById("editItemsContainer").addEventListener("touchend", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
}, { passive: true });

document.getElementById("editItemsContainer").addEventListener("touchcancel", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
}, { passive: true });

document.getElementById("editItemsContainer").addEventListener("click", (event) => {
  const target = event.target.closest("[data-action='delete-item']") || event.target.closest("[data-action='toggle-status']");
  if (!target) return;

  if (target.dataset.action === "delete-item") {
    deleteItem(target.dataset.itemId);
    return;
  }

  if (target.dataset.longPressTriggered === "true") {
    target.dataset.longPressTriggered = "false";
    clearStatusHold(target);
    return;
  }

  const list = getCurrentList();
  const item = list?.items.find((entry) => entry.id === target.dataset.itemId);
  if (!item) return;
  const nextStatus = getNextPurchaseStatus(getItemPurchaseStatus(item));
  applyPurchaseStatus(item, nextStatus, list?.id);
});

document.getElementById("locationTags").addEventListener("click", (event) => {
  const target = event.target.closest("[data-action='remove-location']");
  if (!target) return;
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、場所候補の編集はできません。")) return;
  const locationName = target.textContent.trim();
  list.locations = list.locations.filter((location) => location !== locationName);
  list.items.forEach((item) => {
    if (item.location === locationName) {
      item.location = "";
    }
  });
  saveState();
  render();
});

document.getElementById("addLocationBtn").addEventListener("click", () => {
  const list = getCurrentList();
  if (!list || !requireEditAccess(list, "閲覧モードのため、場所候補の追加はできません。")) return;
  const input = document.getElementById("locationInput");
  const value = input.value.trim();
  if (!list || !value) return;
  if (!list.locations.includes(value)) {
    list.locations.push(value);
  }
  input.value = "";
  saveState();
  render();
});

document.getElementById("locationInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    document.getElementById("addLocationBtn").click();
  }
});

document.getElementById("locationFilterSelect").addEventListener("change", (event) => {
  state.filters.location = event.target.value;
  saveState();
  render();
});

document.getElementById("onlyTodoCheckbox").addEventListener("change", (event) => {
  state.filters.showOnlyTodo = event.target.checked;
  saveState();
  render();
});

document.getElementById("sortSelect").addEventListener("change", (event) => {
  state.filters.sortBy = event.target.value;
  saveState();
  render();
});

document.getElementById("itemsList").addEventListener("mousedown", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  startStatusHold(target, target.dataset.itemId);
});

document.getElementById("itemsList").addEventListener("mouseup", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
});

document.getElementById("itemsList").addEventListener("mouseleave", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
});

document.getElementById("itemsList").addEventListener("touchstart", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  startStatusHold(target, target.dataset.itemId);
}, { passive: true });

document.getElementById("itemsList").addEventListener("touchend", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
}, { passive: true });

document.getElementById("itemsList").addEventListener("touchcancel", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  clearStatusHold(target);
}, { passive: true });

document.getElementById("itemsList").addEventListener("click", (event) => {
  const target = event.target.closest("[data-action='toggle-status']");
  if (!target) return;
  if (target.dataset.longPressTriggered === "true") {
    target.dataset.longPressTriggered = "false";
    clearStatusHold(target);
    return;
  }
  const list = getCurrentList();
  const item = list?.items.find((entry) => entry.id === target.dataset.itemId);
  if (!item) return;
  const nextStatus = getNextPurchaseStatus(getItemPurchaseStatus(item));
  applyPurchaseStatus(item, nextStatus, list?.id);
});

window.addEventListener("hashchange", handleHashChange);

function openChangePwModal() {
  const modal = document.getElementById("changePwModal");
  document.getElementById("newPwInput").value = "";
  document.getElementById("confirmNewPwInput").value = "";
  modal.classList.remove("hidden");
  document.getElementById("newPwInput").focus();
}

function closeChangePwModal() {
  document.getElementById("changePwModal").classList.add("hidden");
}

function handleChangePw() {
  const newPw = document.getElementById("newPwInput").value;
  const confirmPw = document.getElementById("confirmNewPwInput").value;
  if (!newPw || newPw !== confirmPw) {
    alert("パスワードが一致しません。");
    return;
  }
  state.password = newPw;
  saveState();
  closeChangePwModal();
  alert("パスワードを変更しました。");
}

function handleDeleteRoom() {
  if (!confirm("全てのリストを削除します。この操作は取り消せません。よろしいですか？")) return;
  state.lists = [];
  state.currentListId = null;
  state.history = { undo: [], redo: [] };
  state.undoState = null;
  saveState();
  render();
}

document.getElementById("changePwBtn").addEventListener("click", openChangePwModal);
document.getElementById("deleteRoomBtn").addEventListener("click", handleDeleteRoom);
document.getElementById("cancelChangePwBtn").addEventListener("click", closeChangePwModal);
document.getElementById("confirmChangePwBtn").addEventListener("click", handleChangePw);

async function initializeApp() {
  state = loadStateFromLocal();
  // sessionRole is a module-level variable; always start unauthenticated
  sessionRole = null;
  render();
  await loadStateFromServer();
  sessionRole = null;
  render();
  updateUrl(true);
  window.setInterval(() => {
    void loadStateFromServer();
  }, 5000);
}

void initializeApp();
