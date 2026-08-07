/*
==========================================================
Migration OSINT Dashboard

File:
js/utils.js

Description:
Common frontend utility functions used by all dashboard modules.

Dependencies:
None

==========================================================
*/

"use strict";

/* ==========================================================
   VALUES
========================================================== */

export function safeValue(value, fallback = "-") {

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return fallback;
    }

    return value;
}


/* ==========================================================
   NUMBER FORMAT
========================================================== */

export function formatNumber(value) {

    const number = Number(value);

    if (Number.isNaN(number)) {
        return "-";
    }

    return number.toLocaleString("en-US");
}


export function formatPercent(value, decimals = 1) {

    const number = Number(value);

    if (Number.isNaN(number)) {
        return "-";
    }

    return `${number.toFixed(decimals)}%`;
}


/* ==========================================================
   DATE FORMAT
========================================================== */

export function formatDateTime(value) {

    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return value;
    }

    return date.toLocaleString(
        "hu-HU",
        {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit"
        }
    );
}


/* ==========================================================
   STRING
========================================================== */

export function capitalize(text) {

    if (!text) {
        return "";
    }

    return (
        text.charAt(0).toUpperCase() +
        text.slice(1).toLowerCase()
    );
}


export function truncateText(
    text,
    maxLength = 120
) {

    if (!text) {
        return "";
    }

    if (text.length <= maxLength) {
        return text;
    }

    return `${text.substring(0, maxLength)}...`;
}


/* ==========================================================
   HTML
========================================================== */

export function escapeHtml(text) {

    if (!text) {
        return "";
    }

    return text
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


/* ==========================================================
   ARRAYS
========================================================== */

export function normalizeArray(value) {

    if (!value) {
        return [];
    }

    if (Array.isArray(value)) {
        return value;
    }

    return [value];
}


/* ==========================================================
   CONFIDENCE
========================================================== */

export function confidenceClass(confidence) {

    const value = Number(confidence);

    if (value >= 0.75) {
        return "confidence-high";
    }

    if (value >= 0.50) {
        return "confidence-medium";
    }

    return "confidence-low";
}


export function confidenceLabel(confidence) {

    const value = Number(confidence);

    if (value >= 0.75) {
        return "HIGH";
    }

    if (value >= 0.50) {
        return "MEDIUM";
    }

    return "LOW";
}


export function createConfidenceBadge(confidence) {

    const css = confidenceClass(confidence);

    const label = confidenceLabel(confidence);

    return `
        <span class="confidence-badge ${css}">
            ${label}
        </span>
    `;
}


/* ==========================================================
   STATUS
========================================================== */

export function statusClass(status) {

    if (!status) {
        return "status-inactive";
    }

    if (status.toUpperCase() === "ACTIVE") {
        return "status-active";
    }

    return "status-inactive";
}


export function createStatusBadge(status) {

    return `
        <span class="status-badge ${statusClass(status)}">
            ${escapeHtml(status)}
        </span>
    `;
}


/* ==========================================================
   DOM
========================================================== */

export function clearElement(element) {

    if (!element) {
        return;
    }

    element.innerHTML = "";
}


export function showEmptyState(
    element,
    text = "No data available."
) {

    if (!element) {
        return;
    }

    element.innerHTML =
        `
        <div class="empty-state">
            ${escapeHtml(text)}
        </div>
        `;
}


/* ==========================================================
   CLIPBOARD
========================================================== */

export async function copyToClipboard(text) {

    try {

        await navigator.clipboard.writeText(text);

        return true;

    } catch {

        return false;
    }

}


/* ==========================================================
   DOWNLOAD
========================================================== */

export function downloadJson(
    data,
    filename = "dashboard-data.json"
) {

    const blob = new Blob(
        [
            JSON.stringify(
                data,
                null,
                2
            )
        ],
        {
            type: "application/json"
        }
    );

    const url =
        URL.createObjectURL(blob);

    const link =
        document.createElement("a");

    link.href = url;

    link.download = filename;

    link.click();

    URL.revokeObjectURL(url);
}


/* ==========================================================
   TIMING
========================================================== */

export function sleep(milliseconds) {

    return new Promise(
        resolve =>
            setTimeout(
                resolve,
                milliseconds
            )
    );
}


export function debounce(
    callback,
    delay = 300
) {

    let timeout;

    return (...args) => {

        clearTimeout(timeout);

        timeout =
            setTimeout(
                () => callback(...args),
                delay
            );

    };

}
