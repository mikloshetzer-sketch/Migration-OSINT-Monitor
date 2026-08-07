/*
==========================================================
Migration OSINT Dashboard

File:
js/api.js

Description:
Loads dashboard JSON data from GitHub Pages.

Dependencies:
utils.js

==========================================================
*/

"use strict";

import {
    sleep
} from "./utils.js";


const DASHBOARD_DATA_URL =
    "./dashboard-data.json";


const DEFAULT_TIMEOUT =
    10000;


/* ==========================================================
   FETCH WITH TIMEOUT
========================================================== */

async function fetchWithTimeout(
    resource,
    timeout = DEFAULT_TIMEOUT
) {

    const controller =
        new AbortController();

    const timeoutId =
        setTimeout(
            () => controller.abort(),
            timeout
        );

    try {

        const response =
            await fetch(
                resource,
                {
                    cache: "no-cache",
                    signal: controller.signal
                }
            );

        clearTimeout(timeoutId);

        return response;

    }
    catch (error) {

        clearTimeout(timeoutId);

        throw error;

    }

}


/* ==========================================================
   LOAD DASHBOARD
========================================================== */

export async function loadDashboardData() {

    const response =
        await fetchWithTimeout(
            DASHBOARD_DATA_URL
        );

    if (!response.ok) {

        throw new Error(
            `Dashboard JSON loading failed (${response.status})`
        );

    }

    return await response.json();

}


/* ==========================================================
   RETRY LOADER
========================================================== */

export async function loadDashboardDataRetry(
    retries = 3,
    delay = 1500
) {

    let lastError = null;

    for (
        let i = 0;
        i < retries;
        i++
    ) {

        try {

            return await loadDashboardData();

        }

        catch (error) {

            lastError = error;

            if (i < retries - 1) {

                await sleep(delay);

            }

        }

    }

    throw lastError;

}


/* ==========================================================
   VALIDATION
========================================================== */

export function validateDashboardData(data) {

    if (!data) {

        throw new Error(
            "Dashboard JSON is empty."
        );

    }

    if (!data.kpis) {

        throw new Error(
            "Missing KPI section."
        );

    }

    if (!Array.isArray(data.live_events)) {

        throw new Error(
            "Missing live_events."
        );

    }

    if (!Array.isArray(data.event_groups)) {

        throw new Error(
            "Missing event_groups."
        );

    }

    if (!Array.isArray(data.region_activity)) {

        throw new Error(
            "Missing region_activity."
        );

    }

    if (!Array.isArray(data.source_activity)) {

        throw new Error(
            "Missing source_activity."
        );

    }

    if (!data.correlation) {

        throw new Error(
            "Missing correlation section."
        );

    }

    if (!Array.isArray(data.high_confidence_events)) {

        throw new Error(
            "Missing high_confidence_events."
        );

    }

    return true;

}


/* ==========================================================
   COMPLETE LOADER
========================================================== */

export async function getDashboardData() {

    const data =
        await loadDashboardDataRetry();

    validateDashboardData(data);

    return data;

}
