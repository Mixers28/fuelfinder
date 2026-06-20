/*
 * Gmail -> Railway Fuel Finder CSV importer.
 *
 * Apps Script setup:
 * 1. Paste this file into script.google.com.
 * 2. Run setFuelFinderImportConfig once with your Railway import URL and admin token.
 * 3. Create Gmail label "fuel-finder-csv" and filter Fuel Finder emails into it.
 * 4. Run installHourlyFuelFinderTrigger once.
 */

const SOURCE_LABEL = "fuel-finder-csv";
const DONE_LABEL = "fuel-finder-imported";
const ERROR_LABEL = "fuel-finder-import-error";
const FUEL_FINDER_SENDER = "fuel.finder@notifications.service.gov.uk";
const FUEL_FINDER_SUBJECT = "UPDATED FUEL PRICES";
const CSV_NAME_PREFIX = "UpdatedFuelPrice";
const CSV_DOWNLOAD_URL_PATTERN = /https:\/\/www\.fuel-finder\.service\.gov\.uk\/internal\/v[0-9.]+\/csv\/get-latest-fuel-prices-csv/g;

function setFuelFinderImportConfig(importUrl, adminToken) {
  if (!importUrl || !adminToken) {
    throw new Error("Usage: setFuelFinderImportConfig(importUrl, adminToken)");
  }
  PropertiesService.getScriptProperties().setProperties({
    FUEL_FINDER_IMPORT_URL: importUrl,
    FUEL_FINDER_ADMIN_TOKEN: adminToken,
  });
}

function installHourlyFuelFinderTrigger() {
  ScriptApp.getProjectTriggers()
    .filter((trigger) => trigger.getHandlerFunction() === "importLatestFuelFinderCsv")
    .forEach((trigger) => ScriptApp.deleteTrigger(trigger));

  ScriptApp.newTrigger("importLatestFuelFinderCsv")
    .timeBased()
    .everyHours(1)
    .create();
}

function importLatestFuelFinderCsv() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) {
    return;
  }

  try {
    const props = PropertiesService.getScriptProperties();
    const importUrl = props.getProperty("FUEL_FINDER_IMPORT_URL");
    const adminToken = props.getProperty("FUEL_FINDER_ADMIN_TOKEN");
    if (!importUrl || !adminToken) {
      throw new Error("Missing FUEL_FINDER_IMPORT_URL or FUEL_FINDER_ADMIN_TOKEN script property");
    }

    const doneLabel = getOrCreateLabel_(DONE_LABEL);
    const errorLabel = getOrCreateLabel_(ERROR_LABEL);
    const threads = getCandidateThreads_();
    console.log(`Candidate Fuel Finder threads: ${threads.length}`);

    for (const thread of threads) {
      const importable = findImportableCsv_(thread);
      if (!importable) {
        console.log(`No CSV link or attachment found in: ${thread.getFirstMessageSubject()}`);
        continue;
      }

      const response = postImportableCsv_(importUrl, adminToken, importable);

      const status = response.getResponseCode();
      const body = response.getContentText();
      if (status < 200 || status >= 300) {
        thread.addLabel(errorLabel);
        throw new Error(`Fuel Finder CSV import failed for ${importable.name}: ${status} ${body}`);
      }

      thread.removeLabel(errorLabel);
      thread.addLabel(doneLabel);
      console.log(`Imported ${importable.name}: ${body}`);
      return;
    }

    console.log("No unprocessed Fuel Finder CSV emails found.");
  } finally {
    lock.releaseLock();
  }
}

function debugFuelFinderImportSearch() {
  const threads = getCandidateThreads_();
  console.log(`Candidate Fuel Finder threads: ${threads.length}`);

  for (const thread of threads) {
    console.log(`Subject: ${thread.getFirstMessageSubject()}`);
    console.log(`Labels: ${thread.getLabels().map((label) => label.getName()).join(", ")}`);
    const importable = findImportableCsv_(thread);
    console.log(`Importable CSV found: ${Boolean(importable)}${importable ? ` (${importable.name}, ${importable.bytes.length} bytes)` : ""}`);
  }
}

function getCandidateThreads_() {
  const queries = [
    `label:${SOURCE_LABEL} -label:${DONE_LABEL} newer_than:30d`,
    `from:${FUEL_FINDER_SENDER} subject:"${FUEL_FINDER_SUBJECT}" -label:${DONE_LABEL} newer_than:30d`,
  ];
  const seen = {};
  const threads = [];

  for (const query of queries) {
    const found = GmailApp.search(query, 0, 20);
    console.log(`Query "${query}" found ${found.length} thread(s)`);
    for (const thread of found) {
      const id = thread.getId();
      if (!seen[id]) {
        seen[id] = true;
        threads.push(thread);
      }
    }
  }
  return threads;
}

function findImportableCsv_(thread) {
  return findCsvAttachment_(thread) || findCsvDownload_(thread);
}

function postImportableCsv_(importUrl, adminToken, importable) {
  const normalizedImportUrl = importUrl.replace(/\/+$/, "");
  if (importable.bytes) {
    console.log(`Posting CSV bytes to ${normalizedImportUrl}`);
    return UrlFetchApp.fetch(normalizedImportUrl, {
      method: "post",
      contentType: "text/csv",
      payload: importable.bytes,
      headers: {
        "x-admin-token": adminToken,
      },
      muteHttpExceptions: true,
    });
  }

  const urlImportUrl = normalizedImportUrl.endsWith("/fuel-finder-csv")
    ? normalizedImportUrl.replace(/\/fuel-finder-csv$/, "/fuel-finder-csv-url")
    : `${normalizedImportUrl}/admin/import/fuel-finder-csv-url`;
  console.log(`Posting CSV download URL to ${urlImportUrl}`);
  return UrlFetchApp.fetch(urlImportUrl, {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify({ url: importable.url }),
    headers: {
      "x-admin-token": adminToken,
    },
    muteHttpExceptions: true,
  });
}

function findCsvAttachment_(thread) {
  const messages = thread.getMessages().reverse();
  for (const message of messages) {
    const attachments = message.getAttachments({ includeInlineImages: false, includeAttachments: true });
    for (const attachment of attachments) {
      const name = attachment.getName();
      if (name.startsWith(CSV_NAME_PREFIX) && name.toLowerCase().endsWith(".csv")) {
        return { bytes: attachment.getBytes(), name };
      }
    }
  }
  return null;
}

function findCsvDownload_(thread) {
  const messages = thread.getMessages().reverse();
  for (const message of messages) {
    const body = `${message.getPlainBody()}\n${message.getBody()}`;
    const urls = body.match(CSV_DOWNLOAD_URL_PATTERN) || [];
    if (!urls.length) {
      continue;
    }

    const csvUrl = urls[0];
    const response = UrlFetchApp.fetch(csvUrl, {
      method: "get",
      followRedirects: true,
      muteHttpExceptions: true,
      headers: {
        "accept": "text/csv,*/*",
      },
    });

    const status = response.getResponseCode();
    if (status >= 200 && status < 300) {
      return {
        bytes: response.getBlob().getBytes(),
        name: "latest-fuel-finder-prices.csv",
      };
    }

    console.log(`Apps Script CSV download failed with ${status}; asking backend to download ${csvUrl}`);
    return {
      bytes: null,
      name: "latest-fuel-finder-prices-url",
      url: csvUrl,
    };
  }
  return null;
}

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}
