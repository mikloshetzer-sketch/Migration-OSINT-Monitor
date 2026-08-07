/*
==========================================================
Migration OSINT Dashboard

File:
js/ui.js

Description:
UI helper functions.

Dependencies:
utils.js

==========================================================
*/

"use strict";

import {
    formatDateTime
} from "./utils.js";


const globalMessage =
    document.getElementById(
        "globalMessage"
    );

const updatedAt =
    document.getElementById(
        "updatedAt"
    );

const refreshButton =
    document.getElementById(
        "refreshButton"
    );

const systemStatus =
    document.getElementById(
        "systemStatus"
    );


/* ==========================================================
   GLOBAL MESSAGE
========================================================== */

export function hideMessage() {

    if (!globalMessage) {
        return;
    }

    globalMessage.className =
        "global-message hidden";

    globalMessage.innerHTML = "";

}


export function showSuccess(message) {

    showMessage(
        message,
        "success"
    );

}


export function showError(message) {

    showMessage(
        message,
        "error"
    );

}


export function showInfo(message) {

    showMessage(
        message,
        ""
    );

}


function showMessage(
    message,
    type
) {

    if (!globalMessage) {
        return;
    }

    globalMessage.className =
        `global-message ${type}`;

    globalMessage.innerHTML =
        message;

    setTimeout(
        hideMessage,
        5000
    );

}


/* ==========================================================
   UPDATED TIME
========================================================== */

export function setUpdatedTime(value) {

    if (!updatedAt) {
        return;
    }

    updatedAt.textContent =
        formatDateTime(value);

}


/* ==========================================================
   SYSTEM STATUS
========================================================== */

export function setStatusLoading() {

    if (!systemStatus) {
        return;
    }

    systemStatus.innerHTML =
        `
        <span class="status-dot"></span>
        Loading...
        `;

}


export function setStatusLive() {

    if (!systemStatus) {
        return;
    }

    systemStatus.innerHTML =
        `
        <span class="status-dot"></span>
        OSINT LIVE
        `;

}


export function setStatusError() {

    if (!systemStatus) {
        return;
    }

    systemStatus.innerHTML =
        `
        <span class="status-dot"></span>
        ERROR
        `;

}


/* ==========================================================
   REFRESH BUTTON
========================================================== */

export function setRefreshHandler(handler) {

    if (!refreshButton) {
        return;
    }

    refreshButton.onclick =
        handler;

}


export function disableRefresh() {

    if (!refreshButton) {
        return;
    }

    refreshButton.disabled = true;

    refreshButton.textContent =
        "Frissítés...";

}


export function enableRefresh() {

    if (!refreshButton) {
        return;
    }

    refreshButton.disabled = false;

    refreshButton.textContent =
        "Adatok frissítése";

}


/* ==========================================================
   LOADING
========================================================== */

export function beginLoading() {

    disableRefresh();

    setStatusLoading();

}


export function finishLoading() {

    enableRefresh();

    setStatusLive();

}


export function loadingFailed() {

    enableRefresh();

    setStatusError();

}
