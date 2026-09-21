(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("room-data")?.textContent || "{}");
  const list = document.getElementById("speaker-list");
  const orderInput = document.getElementById("manual_order");
  if (!list || !orderInput) return;

  let dragged = null;
  const refreshOrder = () => {
    const cards = [...list.querySelectorAll(".speaker")];
    orderInput.value = cards.map(card => card.dataset.id).join(",");
    cards.forEach((card, index) => {
      const node = card.querySelector(".speaker-number");
      if (node) node.textContent = String(index + 1);
    });
  };

  const move = (card, direction) => {
    if (direction < 0) {
      const previous = card.previousElementSibling;
      if (previous) list.insertBefore(card, previous);
    } else {
      const next = card.nextElementSibling;
      if (next) list.insertBefore(next, card);
    }
    refreshOrder();
  };

  const chooseDelete = () => new Promise(resolve => {
    const dialog = document.createElement("dialog");
    dialog.className = "dialog";
    dialog.innerHTML = `<form method="dialog" class="dialog-card"><h2>حذف سخنران</h2><p>فایل ضبط این سخنران را نگه می‌دارید یا حذف می‌کنید؟</p><div class="row center"><button class="secondary" value="cancel">انصراف</button><button class="secondary" value="discard">حذف ضبط و سخنران</button><button class="primary" value="save">ذخیره ضبط و حذف سخنران</button></div></form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("close", () => { const value = dialog.returnValue || "cancel"; dialog.remove(); resolve(value); }, {once:true});
    dialog.showModal();
  });

  list.querySelectorAll(".speaker").forEach(card => {
    card.addEventListener("dragstart", event => {
      dragged = card;
      card.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", card.dataset.id);
    });
    card.addEventListener("dragend", () => {
      dragged = null;
      card.classList.remove("dragging");
      list.querySelectorAll(".drop-target").forEach(node => node.classList.remove("drop-target"));
      refreshOrder();
    });
    card.addEventListener("dragover", event => {
      event.preventDefault();
      if (!dragged || dragged === card) return;
      card.classList.add("drop-target");
      const rect = card.getBoundingClientRect();
      if (event.clientY > rect.top + rect.height / 2) list.insertBefore(dragged, card.nextSibling);
      else list.insertBefore(dragged, card);
    });
    card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
    card.querySelector(".speaker-up")?.addEventListener("click", () => move(card, -1));
    card.querySelector(".speaker-down")?.addEventListener("click", () => move(card, 1));
  });

  document.querySelectorAll(".copy-public-link").forEach(button => button.addEventListener("click", async () => {
    const input = document.querySelector(button.dataset.target);
    if (!input) return;
    try {
      await navigator.clipboard.writeText(input.value);
      button.textContent = "کپی شد";
      setTimeout(() => button.textContent = "کپی", 1300);
    } catch (_) {
      input.select();
      document.execCommand("copy");
    }
  }));

  document.querySelectorAll(".delete-file").forEach(button => button.addEventListener("click", async () => {
    if (!window.confirm("این فایل حذف شود؟")) return;
    button.disabled = true;
    try {
      const form = new FormData();
      form.append("csrf", data.csrf || "");
      const response = await fetch(`/files/${button.dataset.fileId}/delete`, {method:"POST", body:form, credentials:"same-origin", headers:{Accept:"application/json"}});
      if (response.status === 401) { window.location.assign("/login"); return; }
      if (!response.ok) throw new Error();
      window.location.reload();
    } catch (_) {
      button.disabled = false;
      window.alert("حذف فایل ناموفق بود.");
    }
  }));

  document.querySelectorAll(".delete-speaker").forEach(button => button.addEventListener("click", async () => {
    const choice = await chooseDelete();
    if (choice === "cancel") return;
    button.disabled = true;
    try {
      const form = new FormData();
      form.append("csrf", data.csrf || "");
      form.append("save_recording", choice === "save" ? "1" : "0");
      const response = await fetch(`/api/rooms/${data.roomId}/speakers/${button.dataset.speakerId}/delete`, {method:"POST", body:form, credentials:"same-origin", headers:{Accept:"application/json"}});
      if (response.status === 401) { window.location.assign("/login"); return; }
      let body = null; try { body = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error(body?.detail || "حذف سخنران ناموفق بود.");
      window.location.reload();
    } catch (error) {
      button.disabled = false;
      window.alert(error.message || "حذف سخنران ناموفق بود.");
    }
  }));

  refreshOrder();
})();
