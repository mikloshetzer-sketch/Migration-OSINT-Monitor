/*
==========================================================
Migration OSINT Dashboard

File:
js/tables.js

Description:
Renders all dashboard tables:

- Live Event Feed
- Top Event Groups
- High Confidence Events

Dependencies:
utils.js

==========================================================
*/

"use strict";

import {
    escapeHtml,
    formatDateTime,
    safeValue,
    truncateText,
    createConfidenceBadge,
    createStatusBadge
} from "./utils.js";


/* ==========================================================
   CONSTANTS
========================================================== */

const LIVE_EVENTS_TABLE_ID =
    "liveEventsTable";

const EVENT_GROUPS_TABLE_ID =
    "eventGroupsTable";

const HIGH_CONFIDENCE_TABLE_ID =
    "highConfidenceTable";


/* ==========================================================
   PUBLIC API
========================================================== */

export function renderTables(data) {

    renderLiveEvents(
        data?.live_events || []
    );

    renderEventGroups(
        data?.event_groups || []
    );

    renderHighConfidenceEvents(
        data?.high_confidence_events || []
    );

}


/* ==========================================================
   LIVE EVENT FEED
========================================================== */

export function renderLiveEvents(events) {

    const tableBody =
        document.getElementById(
            LIVE_EVENTS_TABLE_ID
        );

    if (!tableBody) {
        return;
    }

    tableBody.innerHTML = "";

    if (
        !Array.isArray(events) ||
        events.length === 0
    ) {

        tableBody.innerHTML =
            createTableEmptyRow(
                6,
                "Nincs megjeleníthető operatív esemény."
            );

        return;
    }

    events.forEach(
        event => {

            const row =
                createLiveEventRow(
                    event
                );

            tableBody.insertAdjacentHTML(
                "beforeend",
                row
            );

        }
    );

}


function createLiveEventRow(event) {

    const id =
        safeValue(
            event?.id
        );

    const eventGroupId =
        safeValue(
            event?.event_group_id,
            null
        );

    const publishedAt =
        formatDateTime(
            event?.published_at
        );

    const eventType =
        safeValue(
            event?.event_type
        );

    const location =
        safeValue(
            event?.location
        );

    const confidence =
        Number(
            event?.confidence || 0
        );

    const source =
        safeValue(
            event?.source
        );

    const author =
        safeValue(
            event?.author
        );

    const text =
        safeValue(
            event?.text,
            ""
        );

    const url =
        safeValue(
            event?.url,
            ""
        );

    const correlationScore =
        event?.correlation_score;

    const tooltipParts = [];

    if (author && author !== "-") {
        tooltipParts.push(
            `Author: ${author}`
        );
    }

    if (eventGroupId) {
        tooltipParts.push(
            `Event Group: #${eventGroupId}`
        );
    }

    if (
        correlationScore !== null &&
        correlationScore !== undefined
    ) {
        tooltipParts.push(
            `Correlation: ${Number(
                correlationScore
            ).toFixed(2)}`
        );
    }

    if (text) {
        tooltipParts.push(
            text
        );
    }

    const tooltip =
        escapeHtml(
            tooltipParts.join(
                "\n"
            )
        );

    const sourceCell =
        createSourceCell(
            source,
            url
        );

    return `
        <tr
            title="${tooltip}"
            data-event-id="${escapeHtml(
                String(id)
            )}"
        >
            <td class="table-id">
                #${escapeHtml(
                    String(id)
                )}
            </td>

            <td class="table-time">
                ${escapeHtml(
                    publishedAt
                )}
            </td>

            <td class="table-event-type">
                ${escapeHtml(
                    eventType
                )}
            </td>

            <td>
                ${escapeHtml(
                    location
                )}
            </td>

            <td>
                ${createConfidenceBadge(
                    confidence
                )}
            </td>

            <td>
                ${sourceCell}
            </td>
        </tr>
    `;
}


/* ==========================================================
   EVENT GROUPS
========================================================== */

export function renderEventGroups(groups) {

    const tableBody =
        document.getElementById(
            EVENT_GROUPS_TABLE_ID
        );

    if (!tableBody) {
        return;
    }

    tableBody.innerHTML = "";

    if (
        !Array.isArray(groups) ||
        groups.length === 0
    ) {

        tableBody.innerHTML =
            createTableEmptyRow(
                7,
                "Még nincs EventGroup az adatbázisban."
            );

        return;
    }

    groups.forEach(
        group => {

            const row =
                createEventGroupRow(
                    group
                );

            tableBody.insertAdjacentHTML(
                "beforeend",
                row
            );

        }
    );

}


function createEventGroupRow(group) {

    const id =
        safeValue(
            group?.id
        );

    const eventType =
        safeValue(
            group?.event_type
        );

    const title =
        safeValue(
            group?.title,
            ""
        );

    const region =
        safeValue(
            group?.primary_region,
            "GLOBAL"
        );

    const location =
        safeValue(
            group?.primary_location
        );

    const country =
        safeValue(
            group?.country
        );

    const lastSeen =
        formatDateTime(
            group?.last_seen
        );

    const firstSeen =
        formatDateTime(
            group?.first_seen
        );

    const sourceCount =
        Number(
            group?.source_count || 0
        );

    const sourceTypes =
        Array.isArray(
            group?.source_types
        )
            ? group.source_types
            : [];

    const status =
        safeValue(
            group?.status,
            "ACTIVE"
        );

    const confidence =
        Number(
            group?.confidence || 0
        );

    const representativeText =
        safeValue(
            group?.representative_text,
            ""
        );

    const tooltipParts = [];

    if (title) {
        tooltipParts.push(
            title
        );
    }

    if (
        location &&
        location !== "-"
    ) {
        tooltipParts.push(
            `Location: ${location}`
        );
    }

    if (
        country &&
        country !== "-"
    ) {
        tooltipParts.push(
            `Country: ${country}`
        );
    }

    if (firstSeen !== "-") {
        tooltipParts.push(
            `First seen: ${firstSeen}`
        );
    }

    if (
        sourceTypes.length > 0
    ) {
        tooltipParts.push(
            `Sources: ${sourceTypes.join(", ")}`
        );
    }

    if (representativeText) {
        tooltipParts.push(
            representativeText
        );
    }

    const tooltip =
        escapeHtml(
            tooltipParts.join(
                "\n"
            )
        );

    return `
        <tr
            title="${tooltip}"
            data-event-group-id="${escapeHtml(
                String(id)
            )}"
        >
            <td class="table-id">
                #${escapeHtml(
                    String(id)
                )}
            </td>

            <td class="table-event-type">
                ${escapeHtml(
                    eventType
                )}
            </td>

            <td>
                ${escapeHtml(
                    region
                )}
            </td>

            <td class="table-time">
                ${escapeHtml(
                    lastSeen
                )}
            </td>

            <td>
                ${escapeHtml(
                    String(sourceCount)
                )}
            </td>

            <td>
                ${createConfidenceBadge(
                    confidence
                )}
            </td>

            <td>
                ${createStatusBadge(
                    status
                )}
            </td>
        </tr>
    `;
}


/* ==========================================================
   HIGH CONFIDENCE EVENTS
========================================================== */

export function renderHighConfidenceEvents(events) {

    const tableBody =
        document.getElementById(
            HIGH_CONFIDENCE_TABLE_ID
        );

    if (!tableBody) {
        return;
    }

    tableBody.innerHTML = "";

    if (
        !Array.isArray(events) ||
        events.length === 0
    ) {

        tableBody.innerHTML =
            createTableEmptyRow(
                9,
                "Jelenleg nincs a konfidenciaküszöböt elérő eseménycsoport."
            );

        return;
    }

    events.forEach(
        event => {

            const row =
                createHighConfidenceRow(
                    event
                );

            tableBody.insertAdjacentHTML(
                "beforeend",
                row
            );

        }
    );

}


function createHighConfidenceRow(event) {

    const id =
        safeValue(
            event?.id
        );

    const lastSeen =
        formatDateTime(
            event?.last_seen
        );

    const eventType =
        safeValue(
            event?.event_type
        );

    const location =
        safeValue(
            event?.primary_location
        );

    const country =
        safeValue(
            event?.country
        );

    const region =
        safeValue(
            event?.region,
            "GLOBAL"
        );

    const confidence =
        Number(
            event?.confidence || 0
        );

    const sourceCount =
        Number(
            event?.source_count || 0
        );

    const representativeText =
        safeValue(
            event?.representative_text,
            ""
        );

    const truncatedText =
        truncateText(
            representativeText,
            150
        );

    return `
        <tr
            title="${escapeHtml(
                representativeText
            )}"
            data-high-confidence-id="${escapeHtml(
                String(id)
            )}"
        >
            <td class="table-id">
                #${escapeHtml(
                    String(id)
                )}
            </td>

            <td class="table-time">
                ${escapeHtml(
                    lastSeen
                )}
            </td>

            <td class="table-event-type">
                ${escapeHtml(
                    eventType
                )}
            </td>

            <td>
                ${escapeHtml(
                    location
                )}
            </td>

            <td>
                ${escapeHtml(
                    country
                )}
            </td>

            <td>
                ${escapeHtml(
                    region
                )}
            </td>

            <td>
                ${createConfidenceBadge(
                    confidence
                )}
            </td>

            <td>
                ${escapeHtml(
                    String(sourceCount)
                )}
            </td>

            <td class="table-text">
                ${escapeHtml(
                    truncatedText
                )}
            </td>
        </tr>
    `;
}


/* ==========================================================
   SOURCE LINK
========================================================== */

function createSourceCell(
    source,
    url
) {

    const safeSource =
        escapeHtml(
            String(
                safeValue(
                    source
                )
            )
        );

    if (
        !url ||
        url === "-"
    ) {

        return safeSource;
    }

    const safeUrl =
        escapeHtml(
            String(url)
        );

    return `
        <a
            class="table-link"
            href="${safeUrl}"
            target="_blank"
            rel="noopener noreferrer"
        >
            ${safeSource}
        </a>
    `;
}


/* ==========================================================
   EMPTY STATE
========================================================== */

function createTableEmptyRow(
    columnCount,
    message
) {

    return `
        <tr>
            <td
                colspan="${columnCount}"
                class="loading-cell"
            >
                ${escapeHtml(
                    message
                )}
            </td>
        </tr>
    `;
}


/* ==========================================================
   RESET
========================================================== */

export function clearTables() {

    clearTable(
        LIVE_EVENTS_TABLE_ID,
        6
    );

    clearTable(
        EVENT_GROUPS_TABLE_ID,
        7
    );

    clearTable(
        HIGH_CONFIDENCE_TABLE_ID,
        9
    );

}


function clearTable(
    tableBodyId,
    columnCount
) {

    const tableBody =
        document.getElementById(
            tableBodyId
        );

    if (!tableBody) {
        return;
    }

    tableBody.innerHTML =
        createTableEmptyRow(
            columnCount,
            "Adatok betöltése..."
        );
}


/* ==========================================================
   SORT HELPERS
========================================================== */

export function sortLiveEvents(
    events
) {

    if (!Array.isArray(events)) {
        return [];
    }

    return [
        ...events
    ].sort(
        (
            a,
            b
        ) => {

            const dateA =
                parseDateValue(
                    a?.published_at
                );

            const dateB =
                parseDateValue(
                    b?.published_at
                );

            return (
                dateB -
                dateA
            );
        }
    );
}


export function sortEventGroups(
    groups
) {

    if (!Array.isArray(groups)) {
        return [];
    }

    return [
        ...groups
    ].sort(
        (
            a,
            b
        ) => {

            const countA =
                Number(
                    a?.source_count || 0
                );

            const countB =
                Number(
                    b?.source_count || 0
                );

            if (
                countA !== countB
            ) {

                return (
                    countB -
                    countA
                );

            }

            const dateA =
                parseDateValue(
                    a?.last_seen
                );

            const dateB =
                parseDateValue(
                    b?.last_seen
                );

            return (
                dateB -
                dateA
            );

        }
    );
}


export function sortHighConfidenceEvents(
    events
) {

    if (!Array.isArray(events)) {
        return [];
    }

    return [
        ...events
    ].sort(
        (
            a,
            b
        ) => {

            const confidenceA =
                Number(
                    a?.confidence || 0
                );

            const confidenceB =
                Number(
                    b?.confidence || 0
                );

            if (
                confidenceA !==
                confidenceB
            ) {

                return (
                    confidenceB -
                    confidenceA
                );

            }

            const dateA =
                parseDateValue(
                    a?.last_seen
                );

            const dateB =
                parseDateValue(
                    b?.last_seen
                );

            return (
                dateB -
                dateA
            );

        }
    );
}


/* ==========================================================
   DATE PARSING
========================================================== */

function parseDateValue(value) {

    if (!value) {
        return 0;
    }

    const normalized =
        normalizeDateString(
            value
        );

    const date =
        new Date(
            normalized
        );

    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return 0;
    }

    return date.getTime();
}


function normalizeDateString(value) {

    if (
        typeof value !==
        "string"
    ) {

        return value;
    }

    const trimmed =
        value.trim();

    /*
    The exporter currently produces:

    2026-08-07 16:30:01

    Browsers are more reliable with:

    2026-08-07T16:30:01Z
    */

    const simpleUtcPattern =
        /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

    if (
        simpleUtcPattern.test(
            trimmed
        )
    ) {

        return (
            trimmed.replace(
                " ",
                "T"
            )
            + "Z"
        );

    }

    return trimmed;
}


/* ==========================================================
   OPTIONAL FILTER HELPERS
========================================================== */

export function filterLiveEventsByType(
    events,
    eventType
) {

    if (!Array.isArray(events)) {
        return [];
    }

    if (!eventType) {
        return events;
    }

    return events.filter(
        event =>
            event?.event_type ===
            eventType
    );
}


export function filterEventGroupsByRegion(
    groups,
    region
) {

    if (!Array.isArray(groups)) {
        return [];
    }

    if (!region) {
        return groups;
    }

    return groups.filter(
        group =>
            group?.primary_region ===
            region
    );
}


export function filterEventGroupsByStatus(
    groups,
    status = "ACTIVE"
) {

    if (!Array.isArray(groups)) {
        return [];
    }

    if (!status) {
        return groups;
    }

    const normalizedStatus =
        String(
            status
        ).toUpperCase();

    return groups.filter(
        group =>
            String(
                group?.status || ""
            ).toUpperCase() ===
            normalizedStatus
    );
}


/* ==========================================================
   TABLE COUNTS
========================================================== */

export function getTableCounts(data) {

    return {
        live_events:
            Array.isArray(
                data?.live_events
            )
                ? data.live_events.length
                : 0,

        event_groups:
            Array.isArray(
                data?.event_groups
            )
                ? data.event_groups.length
                : 0,

        high_confidence_events:
            Array.isArray(
                data?.high_confidence_events
            )
                ? data.high_confidence_events.length
                : 0
    };
}


/* ==========================================================
   FINAL RENDER WITH SORTING
========================================================== */

export function renderSortedTables(data) {

    const liveEvents =
        sortLiveEvents(
            data?.live_events || []
        );

    const eventGroups =
        sortEventGroups(
            data?.event_groups || []
        );

    const highConfidenceEvents =
        sortHighConfidenceEvents(
            data?.high_confidence_events || []
        );

    renderLiveEvents(
        liveEvents
    );

    renderEventGroups(
        eventGroups
    );

    renderHighConfidenceEvents(
        highConfidenceEvents
    );

}
