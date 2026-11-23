"use strict";

// Copy an invite link by clicking it.
document.addEventListener("click", async (event) => {
  const copyable = event.target.closest("[data-copy]");
  if (copyable && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(copyable.dataset.copy);
      const old = copyable.textContent;
      copyable.textContent = "Copied!";
      setTimeout(() => { copyable.textContent = old; }, 1200);
    } catch (_) { /* clipboard blocked; the full link is still visible */ }
    return;
  }

  const danger = event.target.closest("[data-confirm]");
  if (danger && !window.confirm(danger.dataset.confirm)) {
    event.preventDefault();
  }
});

// Invite-link presets fill the form; options can still be combined freely.
const presets = {
  simple: { name: false, expiry: "", uses: "" },
  name: { name: true, expiry: "", uses: "" },
  once: { name: false, expiry: "", uses: "1" },
  full: { name: true, expiry: "", uses: "1" }
};

document.querySelectorAll("[data-preset]").forEach((button) => {
  button.addEventListener("click", () => {
    const preset = Object.assign({}, presets[button.dataset.preset]);
    if (!preset) return;
    if (button.dataset.preset === "full" && !preset.expiry) {
      preset.expiry = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16);
    }
    const name = document.getElementById("invite-name");
    const expiry = document.getElementById("invite-expiry");
    const uses = document.getElementById("invite-uses");
    if (name) name.checked = preset.name;
    if (expiry) expiry.value = preset.expiry;
    if (uses) uses.value = preset.uses;
  });
});

// Upload images as raw binary with headers, so no multipart parsing is needed.
const upload = document.getElementById("image-upload");
const uploadStatus = document.getElementById("upload-status");
if (upload) {
  upload.addEventListener("change", async () => {
    const files = Array.from(upload.files || []);
    const csrf = upload.dataset.csrf;
    let ok = 0;
    for (const file of files) {
      try {
        const response = await fetch(upload.dataset.url, {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": file.name,
            "X-CSRF-Token": csrf
          },
          body: file
        });
        const result = await response.json();
        if (response.ok && result.ok) {
          ok += 1;
        } else if (uploadStatus) {
          uploadStatus.textContent = (file.name + ": " + (result.error || "upload failed"));
          uploadStatus.className = "muted small error-text";
        }
      } catch (_) {
        if (uploadStatus) uploadStatus.textContent = "Upload failed: network error";
      }
    }
    if (ok > 0) window.location.reload();
  });
}

// Site-wide background media upload (pictures and videos).
const mediaUpload = document.getElementById("media-upload");
const mediaStatus = document.getElementById("media-upload-status");
if (mediaUpload) {
  mediaUpload.addEventListener("change", async () => {
    const files = Array.from(mediaUpload.files || []);
    if (!files.length) return;
    let ok = 0;
    for (const file of files) {
      if (mediaStatus) mediaStatus.textContent = "Uploading " + file.name + "...";
      try {
        const response = await fetch(mediaUpload.dataset.url, {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": file.name,
            "X-CSRF-Token": mediaUpload.dataset.csrf
          },
          body: file
        });
        const result = await response.json();
        if (response.ok && result.ok) {
          ok += 1;
        } else if (mediaStatus) {
          mediaStatus.textContent = file.name + ": " + (result.error || "upload failed");
        }
      } catch (_) {
        if (mediaStatus) mediaStatus.textContent = "Upload failed: network error";
      }
    }
    if (ok > 0) window.location.reload();
  });
}

// Nudge the visitor towards the invite lobster after 10 seconds.
const lobsterHint = document.querySelector(".lobster-hint");
const lobsterButton = document.querySelector(".lobster-button");
if (lobsterHint && lobsterButton) {
  const timer = window.setTimeout(() => lobsterHint.classList.add("is-visible"), 10000);
  lobsterButton.addEventListener("click", () => {
    window.clearTimeout(timer);
    lobsterHint.classList.remove("is-visible");
  });
}
