// COLA Label Verifier: the batch page. The spreadsheet and images stay in this browser; each
// label goes to the server on its own, two at a time, and results fill the table as they come.
"use strict";

(function () {
  const sheetInput = document.querySelector("#sheet");
  const imagesInput = document.querySelector("#images");
  const sheetStatus = document.querySelector(".sheet-status");
  const imageStatus = document.querySelector(".image-status");
  const progress = document.querySelector(".batch-progress");
  const bar = progress.querySelector("progress");
  const words = progress.querySelector(".progress-words");
  const summary = document.querySelector(".batch-summary");
  const table = document.querySelector(".batch-results");
  const body = table.querySelector("tbody");
  const exportButton = document.querySelector(".export-results");
  const exportForm = document.querySelector(".export-form");
  const ORDER = ["Does not match", "Couldn't check", "Needs review", "Matches"];
  const AT_ONCE = 2; // the server checks two labels at once
  let rows = [];
  let files = new Map();
  let results = [];
  let running = false;

  function say(element, lines) {
    element.replaceChildren(...lines.map(function (text) {
      const line = document.createElement("p");
      line.textContent = text;
      return line;
    }));
  }

  sheetInput.addEventListener("change", function () {
    if (!sheetInput.files.length) { return; }
    const form = new FormData();
    form.append("sheet", sheetInput.files[0]);
    say(sheetStatus, ["Reading the spreadsheet..."]);
    fetch("/batch/read", { method: "POST", body: form, credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (result) {
        if (result.error) { rows = []; say(sheetStatus, [result.error]); return; }
        rows = result.rows;
        const lines = [rows.length + " labels read from the spreadsheet."];
        rows.forEach(function (row) {
          const problems = Object.values(row.errors);
          if (problems.length) { lines.push("Row " + row.number + ": " + problems.join(" ")); }
        });
        if (result.unknown_columns.length) {
          lines.push("Columns ignored: " + result.unknown_columns.join(", ") + ".");
        }
        say(sheetStatus, lines);
        showImages();
      })
      .catch(function () { say(sheetStatus, ["Couldn't read the spreadsheet. Please try again."]); });
  });

  imagesInput.addEventListener("change", function () {
    files = new Map(Array.from(imagesInput.files).map(function (file) {
      return [file.name.toLowerCase(), file];
    }));
    showImages();
  });

  function missingImages(row) {
    return row.images.filter(function (name) { return !files.has(name.toLowerCase()); });
  }

  function showImages() {
    if (!rows.length) { return; }
    const lines = [files.size + " images chosen."];
    rows.forEach(function (row) {
      const missing = missingImages(row);
      if (missing.length) { lines.push("Row " + row.number + " still needs: " + missing.join(", ")); }
    });
    if (lines.length === 1 && files.size) { lines.push("Every label has its images."); }
    say(imageStatus, lines);
  }

  document.querySelector(".run-batch").addEventListener("click", function () {
    if (!rows.length) { say(sheetStatus, ["Choose the spreadsheet first."]); sheetInput.focus(); return; }
    run(rows);
  });

  document.querySelector(".run-example").addEventListener("click", function () {
    fetch("/batch/samples", { credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (result) { run(result.rows); });
  });

  function warnBeforeLeaving(event) { event.preventDefault(); event.returnValue = ""; }

  function run(list) {
    if (running) { return; }
    running = true;
    results = [];
    body.replaceChildren();
    table.hidden = false;
    exportButton.hidden = true;
    summary.textContent = "";
    progress.hidden = false;
    bar.max = list.length;
    bar.value = 0;
    words.textContent = "0 of " + list.length + " checked";
    window.addEventListener("beforeunload", warnBeforeLeaving);
    const queue = list.slice();
    let done = 0;
    function worker() {
      const row = queue.shift();
      if (!row) { return Promise.resolve(); }
      return check(row).then(function (result) {
        add(row, result);
        done += 1;
        bar.value = done;
        words.textContent = done + " of " + list.length + " checked";
        return worker();
      });
    }
    const workers = [];
    for (let i = 0; i < AT_ONCE; i += 1) { workers.push(worker()); }
    Promise.all(workers).then(function () {
      running = false;
      window.removeEventListener("beforeunload", warnBeforeLeaving);
      finish(list.length);
    });
  }

  function couldNotCheck(reason) { return { verdict: "Couldn't check", issues: reason, items: [] }; }

  function wait(seconds) { return new Promise(function (resolve) { setTimeout(resolve, seconds * 1000); }); }

  function check(row, attempt) {
    attempt = attempt || 0;
    const problems = Object.values(row.errors || {});
    if (problems.length) { return Promise.resolve(couldNotCheck(problems.join(" "))); }
    const form = new FormData();
    Object.entries(row.values).forEach(function ([name, value]) { form.append(name, value); });
    if (row.sample) {
      form.append("sample", row.sample);
    } else {
      const missing = missingImages(row);
      if (missing.length) {
        return Promise.resolve(couldNotCheck("Image " + missing.join(", ") + " wasn't chosen."));
      }
      row.images.forEach(function (name) { form.append("images", files.get(name.toLowerCase())); });
    }
    return fetch("/batch/check", { method: "POST", body: form, credentials: "same-origin" })
      .then(function (response) {
        if ((response.status === 429 || response.status === 503) && attempt < 5) {
          const pause = Number(response.headers.get("Retry-After")) || 5;
          words.textContent = "The server asked to slow down; continuing in " + pause + " seconds...";
          return wait(pause).then(function () { return check(row, attempt + 1); });
        }
        return response.json().then(function (result) {
          if (!response.ok) { return couldNotCheck(result.error || "The server couldn't check it."); }
          const issues = result.items.filter(function (item) { return item.status !== "pass"; })
            .map(function (item) {
              const note = item.notes.length ? " (" + item.notes[item.notes.length - 1] + ")" : "";
              return item.name + ": " + item.status_word + note;
            });
          return { verdict: result.verdict, issues: issues.join("; "), items: result.items };
        });
      })
      .catch(function () { return couldNotCheck("The connection failed."); });
  }

  function add(row, result) {
    const rank = ORDER.indexOf(result.verdict);
    results.push({
      number: row.number, images: row.images, brand: row.values.brand_name || "",
      verdict: result.verdict, issues: result.issues,
    });
    const line = document.createElement("tr");
    line.dataset.rank = String(rank);
    line.dataset.number = String(row.number);
    const cells = [String(row.number), row.values.brand_name || ""].map(function (text) {
      const cell = document.createElement("td");
      cell.textContent = text;
      return cell;
    });
    const verdict = document.createElement("td");
    verdict.className = "verdict-cell verdict-cell-" + rank;
    verdict.textContent = ["✖ ", "! ", "! ", "✔ "][rank] + result.verdict;
    const issues = document.createElement("td");
    issues.textContent = result.issues || "Nothing; every item matches.";
    if (result.items.length) {
      const details = document.createElement("details");
      const label = document.createElement("summary");
      label.textContent = "Every item";
      details.append(label);
      const list = document.createElement("ul");
      result.items.forEach(function (item) {
        const entry = document.createElement("li");
        entry.textContent = item.name + ": " + item.status_word +
          " (application: " + (item.expected || "not stated") + "; label: " + (item.found || "not found") + ")";
        list.append(entry);
      });
      details.append(list);
      issues.append(details);
    }
    line.append(...cells, verdict, issues);
    // Problems first: insert before the first row that ranks lower, or by row number.
    const after = Array.from(body.children).find(function (other) {
      const otherRank = Number(other.dataset.rank);
      return otherRank > rank || (otherRank === rank && Number(other.dataset.number) > row.number);
    });
    body.insertBefore(line, after || null);
  }

  function finish(total) {
    const count = function (verdict) { return results.filter(function (r) { return r.verdict === verdict; }).length; };
    summary.textContent = total + " labels: " + count("Matches") + " match, " + count("Needs review") +
      " need review, " + count("Does not match") + " don't match, " + count("Couldn't check") +
      " couldn't be checked.";
    progress.hidden = true;
    exportButton.hidden = false;
  }

  exportButton.addEventListener("click", function () {
    exportForm.elements.namedItem("results").value = JSON.stringify(results);
    exportForm.submit();
  });
})();
