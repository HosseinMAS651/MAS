(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("room-data")?.textContent || "{}");
  const list = document.getElementById("speaker-list");
  const orderInput = document.getElementById("manual_order");
  if (!list || !orderInput) return;

  let dragged = null;
  const refreshOrder = () => {
    const ids = [...list.querySelectorAll(".speaker")].map(x => x.dataset.id);
    orderInput.value = ids.join(",");
    [...list.querySelectorAll(".speaker-number")].forEach((node, i) => node.textContent = String(i + 1));
  };
  const move = (card, direction) => {
    if (!card) return;
    if (direction === "up" && card.previousElementSibling) list.insertBefore(card, card.previousElementSibling);
    if (direction === "down" && card.nextElementSibling) list.insertBefore(card.nextElementSibling, card);
    refreshOrder();
  };

  [...list.querySelectorAll(".speaker")].forEach(card => {
    card.addEventListener("dragstart", event => {
      dragged = card;
      card.classList.add("dragging");
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.dataset.id);
      }
    });
    card.addEventListener("dragend", () => {
      dragged = null;
      card.classList.remove("dragging");
      list.querySelectorAll(".drop-target").forEach(x => x.classList.remove("drop-target"));
      refreshOrder();
    });
    card.addEventListener("dragover", event => {
      event.preventDefault();
      if (!dragged || dragged === card) return;
      const rect = card.getBoundingClientRect();
      const after = event.clientY > rect.top + rect.height / 2;
      if (after) list.insertBefore(dragged, card.nextSibling);
      else list.insertBefore(dragged, card);
      card.classList.add("drop-target");
      refreshOrder();
    });
    card.addEventListener("dragleave", () => card.classList.remove("drop-target"));
    card.querySelector(".move-up")?.addEventListener("click", () => move(card, "up"));
    card.querySelector(".move-down")?.addEventListener("click", () => move(card, "down"));
  });

  document.querySelectorAll(".delete-file").forEach(button => {
    button.addEventListener("click", async () => {
      if (!confirm("فایل حذف شود؟")) return;
      button.disabled = true;
      try {
        const fd = new FormData();
        fd.append("csrf", data.csrf || "");
        const response = await fetch(`/files/${button.dataset.fileId}/delete`, {method:"POST", body:fd, credentials:"same-origin", headers:{"Accept":"application/json"}});
        if (!response.ok) throw new Error("delete failed");
        location.reload();
      } catch (_) {
        button.disabled = false;
        alert("حذف فایل ناموفق بود. دوباره تلاش کنید.");
      }
    });
  });

  document.querySelectorAll("[data-confirm-form]").forEach(form => {
    form.addEventListener("submit", event => {
      if (!confirm("این اتاق و تمام داده‌ها و فایل‌های آن حذف شود؟ این عملیات قابل بازگشت نیست.")) event.preventDefault();
    });
  });

  refreshOrder();
})();
