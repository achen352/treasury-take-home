// COLA Label Verifier: small, self-hosted page behavior. The page works without it; this adds
// quick upload checks, the "Checking" state, sample loading, zoom and rotation.
"use strict";

(function () {
  const form = document.querySelector(".check-form");

  // Upload checks before sending, with the server's own words. The server checks again.
  if (form) {
    const input = form.querySelector('input[type="file"]');
    const message = form.querySelector(".client-error");
    const maxBytes = Number(form.dataset.maxBytes);
    const maxFiles = Number(form.dataset.maxFiles);

    form.addEventListener("submit", function (event) {
      const files = input ? Array.from(input.files) : [];
      let problem = "";
      if (files.length > maxFiles) {
        problem = form.dataset.tooMany;
      } else if (files.some(function (file) { return file.size > maxBytes; })) {
        problem = form.dataset.tooLarge;
      }
      if (problem) {
        event.preventDefault();
        message.textContent = problem;
        message.hidden = false;
        input.setAttribute("aria-invalid", "true");
        input.focus();
        return;
      }
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      form.querySelector(".checking").hidden = false;
    });

    // The chosen images are listed, so it's clear what will be sent; they can be dropped in too.
    const zone = form.querySelector(".drop-zone");
    const list = form.querySelector(".file-list");
    function listFiles() {
      list.replaceChildren(...Array.from(input.files).map(function (file) {
        const item = document.createElement("li");
        item.textContent = file.name + " (" + (file.size / 1048576).toFixed(1) + " MB)";
        return item;
      }));
      message.hidden = true;
      input.removeAttribute("aria-invalid");
    }
    input.addEventListener("change", listFiles);
    ["dragenter", "dragover"].forEach(function (name) {
      zone.addEventListener(name, function (event) {
        event.preventDefault();
        zone.classList.add("dragging");
      });
    });
    ["dragleave", "drop"].forEach(function (name) {
      zone.addEventListener(name, function () { zone.classList.remove("dragging"); });
    });
    zone.addEventListener("drop", function (event) {
      event.preventDefault();
      if (event.dataTransfer && event.dataTransfer.files.length) {
        input.files = event.dataTransfer.files;
        listFiles();
      }
    });
    form.querySelector(".clear-files").addEventListener("click", function () {
      input.value = "";
      listFiles();
      input.focus();
    });

    // The country is asked for only for imports, and alcohol content is required for spirits.
    const imported = form.querySelector("#imported");
    const countryField = form.querySelector(".country-field");
    const beverage = form.querySelector("#beverage_type");
    const abvMark = form.querySelector(".abv-required");
    function showWhatApplies() {
      countryField.hidden = !imported.checked;
      abvMark.hidden = beverage.value !== "spirits";
      abvMark.nextElementSibling.hidden = beverage.value !== "spirits";
    }
    imported.addEventListener("change", showWhatApplies);
    beverage.addEventListener("change", showWhatApplies);
    showWhatApplies();

    // Pasted application text fills in the fields, and says what it found.
    const status = form.querySelector(".fill-status");
    form.querySelector(".fill-fields").addEventListener("click", function () {
      const body = new FormData();
      body.append("text", form.querySelector("#application_text").value);
      status.textContent = "Reading the pasted text...";
      fetch("/application/parse", { method: "POST", body: body, credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (result) {
          if (result.error) { status.textContent = result.error; return; }
          Object.entries(result.values).forEach(function ([name, value]) {
            const field = form.elements.namedItem(name);
            if (!field) { return; }
            if (field.type === "checkbox") { field.checked = value === "on"; }
            else { field.value = value; }
          });
          showWhatApplies();
          status.textContent = result.filled.length
            ? "Filled in: " + result.filled.join(", ") + "." +
              (result.missing.length ? " Not found in the text: " + result.missing.join(", ") + "." : "")
            : "No application details were recognised. Try lines like \"Brand Name: OLD TOM\".";
        })
        .catch(function () { status.textContent = "Couldn't read the pasted text. Please try again."; });
    });

    // Choosing a sample fills the form with its application.
    const sample = form.querySelector('select[name="sample"]');
    if (sample) {
      sample.addEventListener("change", function () {
        window.location.assign(sample.value ? "/?sample=" + encodeURIComponent(sample.value) : "/");
      });
    }
  }

  // Rotate buttons turn an image (and its outlines) a quarter turn at a time.
  document.querySelectorAll("button.rotate").forEach(function (button) {
    button.addEventListener("click", function () {
      const frame = button.closest("figure").querySelector(".image-frame");
      const current = Number(frame.dataset.turn || 0);
      const next = (current + Number(button.dataset.turn) + 360) % 360;
      frame.classList.remove("turn-90", "turn-180", "turn-270");
      if (next) { frame.classList.add("turn-" + next); }
      frame.dataset.turn = String(next);
    });
  });

  // Zoom shows a result's spot on the label, turned upright if the text runs sideways.
  const dialog = document.querySelector("dialog.zoom-view");
  if (!dialog) { return; }
  const canvas = dialog.querySelector("canvas");
  const heading = dialog.querySelector("h2");

  document.querySelectorAll("button.zoom").forEach(function (button) {
    button.addEventListener("click", function () {
      const figure = document.querySelector('figure[data-index="' + button.dataset.image + '"]');
      const image = figure.querySelector("img");
      const box = button.dataset.box.split(",").map(Number);
      const sideways = button.dataset.sideways === "true";
      drawZoom(image, box, sideways);
      heading.textContent = button.dataset.name + " on the label";
      dialog.showModal();
      dialog.querySelector(".zoom-close").focus();
    });
  });

  function drawZoom(image, box, sideways) {
    // Boxes are in the original image's pixels; the image shown may be scaled down.
    const scale = image.naturalWidth / Number(image.getAttribute("width"));
    const margin = 0.08 * Math.max(box[2], box[3]);
    const sx = Math.max(0, (box[0] - margin) * scale);
    const sy = Math.max(0, (box[1] - margin) * scale);
    const sw = Math.min(image.naturalWidth - sx, (box[2] + 2 * margin) * scale);
    const sh = Math.min(image.naturalHeight - sy, (box[3] + 2 * margin) * scale);
    const fit = Math.min(4, 900 / Math.max(sw, sh));
    const width = Math.round(sw * fit);
    const height = Math.round(sh * fit);
    const context = canvas.getContext("2d");
    if (sideways) {
      canvas.width = height;
      canvas.height = width;
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.translate(height, 0);
      context.rotate(Math.PI / 2);
    } else {
      canvas.width = width;
      canvas.height = height;
      context.setTransform(1, 0, 0, 1, 0, 0);
    }
    context.drawImage(image, sx, sy, sw, sh, 0, 0, width, height);
    canvas.dataset.sideways = String(sideways);
  }
})();
