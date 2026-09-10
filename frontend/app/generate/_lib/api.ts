import type {
  DbFolder,
  GmailEmail,
  GmailEmailDetail,
  GmailLabel,
  ScheduledRecord,
  StoredEmail,
} from "./types";
import { extractEmailAddress } from "./generate-utils";
import { DEFAULT_SETTINGS, type Settings } from "./settings";

// CRITICAL FIX: different URL for server vs browser
export const API =
  typeof window === "undefined"
    ? process.env.INTERNAL_API_BASE_URL || "http://backend:5000"
    : process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

// ----------------- MD5 + helpers (unchanged) -----------------

function md5cycle(x: number[], k: number[]) {
  let [a, b, c, d] = x;

  const ff = (a: number, b: number, c: number, d: number, x: number, s: number, t: number) => {
    a = a + ((b & c) | (~b & d)) + x + t;
    return (((a << s) | (a >>> (32 - s))) + b) | 0;
  };

  const gg = (a: number, b: number, c: number, d: number, x: number, s: number, t: number) => {
    a = a + ((b & d) | (c & ~d)) + x + t;
    return (((a << s) | (a >>> (32 - s))) + b) | 0;
  };

  const hh = (a: number, b: number, c: number, d: number, x: number, s: number, t: number) => {
    a = a + (b ^ c ^ d) + x + t;
    return (((a << s) | (a >>> (32 - s))) + b) | 0;
  };

  const ii = (a: number, b: number, c: number, d: number, x: number, s: number, t: number) => {
    a = a + (c ^ (b | ~d)) + x + t;
    return (((a << s) | (a >>> (32 - s))) + b) | 0;
  };

  a = ff(a, b, c, d, k[0], 7, -680876936);
  d = ff(d, a, b, c, k[1], 12, -389564586);
  c = ff(c, d, a, b, k[2], 17, 606105819);
  b = ff(b, c, d, a, k[3], 22, -1044525330);
  a = ff(a, b, c, d, k[4], 7, -176418897);
  d = ff(d, a, b, c, k[5], 12, 1200080426);
  c = ff(c, d, a, b, k[6], 17, -1473231341);
  b = ff(b, c, d, a, k[7], 22, -45705983);
  a = ff(a, b, c, d, k[8], 7, 1770035416);
  d = ff(d, a, b, c, k[9], 12, -1958414417);
  c = ff(c, d, a, b, k[10], 17, -42063);
  b = ff(b, c, d, a, k[11], 22, -1990404162);
  a = ff(a, b, c, d, k[12], 7, 1804603682);
  d = ff(d, a, b, c, k[13], 12, -40341101);
  c = ff(c, d, a, b, k[14], 17, -1502002290);
  b = ff(b, c, d, a, k[15], 22, 1236535329);

  a = gg(a, b, c, d, k[1], 5, -165796510);
  d = gg(d, a, b, c, k[6], 9, -1069501632);
  c = gg(c, d, a, b, k[11], 14, 643717713);
  b = gg(b, c, d, a, k[0], 20, -373897302);
  a = gg(a, b, c, d, k[5], 5, -701558691);
  d = gg(d, a, b, c, k[10], 9, 38016083);
  c = gg(c, d, a, b, k[15], 14, -660478335);
  b = gg(b, c, d, a, k[4], 20, -405537848);
  a = gg(a, b, c, d, k[9], 5, 568446438);
  d = gg(d, a, b, c, k[14], 9, -1019803690);
  c = gg(c, d, a, b, k[3], 14, -187363961);
  b = gg(b, c, d, a, k[8], 20, 1163531501);
  a = gg(a, b, c, d, k[13], 5, -1444681467);
  d = gg(d, a, b, c, k[2], 9, -51403784);
  c = gg(c, d, a, b, k[7], 14, 1735328473);
  b = gg(b, c, d, a, k[12], 20, -1926607734);

  a = hh(a, b, c, d, k[5], 4, -378558);
  d = hh(d, a, b, c, k[8], 11, -2022574463);
  c = hh(c, d, a, b, k[11], 16, 1839030562);
  b = hh(b, c, d, a, k[14], 23, -35309556);
  a = hh(a, b, c, d, k[1], 4, -1530992060);
  d = hh(d, a, b, c, k[4], 11, 1272893353);
  c = hh(c, d, a, b, k[7], 16, -155497632);
  b = hh(b, c, d, a, k[10], 23, -1094730640);
  a = hh(a, b, c, d, k[13], 4, 681279174);
  d = hh(d, a, b, c, k[0], 11, -358537222);
  c = hh(c, d, a, b, k[3], 16, -722521979);
  b = hh(b, c, d, a, k[6], 23, 76029189);
  a = hh(a, b, c, d, k[9], 4, -640364487);
  d = hh(d, a, b, c, k[12], 11, -421815835);
  c = hh(c, d, a, b, k[15], 16, 530742520);
  b = hh(b, c, d, a, k[2], 23, -995338651);

  a = ii(a, b, c, d, k[0], 6, -198630844);
  d = ii(d, a, b, c, k[7], 10, 1126891415);
  c = ii(c, d, a, b, k[14], 15, -1416354905);
  b = ii(b, c, d, a, k[5], 21, -57434055);
  a = ii(a, b, c, d, k[12], 6, 1700485571);
  d = ii(d, a, b, c, k[3], 10, -1894986606);
  c = ii(c, d, a, b, k[10], 15, -1051523);
  b = ii(b, c, d, a, k[1], 21, -2054922799);
  a = ii(a, b, c, d, k[8], 6, 1873313359);
  d = ii(d, a, b, c, k[15], 10, -30611744);
  c = ii(c, d, a, b, k[6], 15, -1560198380);
  b = ii(b, c, d, a, k[13], 21, 1309151649);
  a = ii(a, b, c, d, k[4], 6, -145523070);
  d = ii(d, a, b, c, k[11], 10, -1120210379);
  c = ii(c, d, a, b, k[2], 15, 718787259);
  b = ii(b, c, d, a, k[9], 21, -343485551);

  x[0] = (x[0] + a) | 0;
  x[1] = (x[1] + b) | 0;
  x[2] = (x[2] + c) | 0;
  x[3] = (x[3] + d) | 0;
}

function md5blk(s: string) {
  const md5blks: number[] = [];
  for (let i = 0; i < 64; i += 4) {
    md5blks[i >> 2] =
      s.charCodeAt(i) +
      (s.charCodeAt(i + 1) << 8) +
      (s.charCodeAt(i + 2) << 16) +
      (s.charCodeAt(i + 3) << 24);
  }
  return md5blks;
}

function md51(s: string) {
  const n = s.length;
  const state = [1732584193, -271733879, -1732584194, 271733878];
  let i: number;

  for (i = 64; i <= n; i += 64) {
    md5cycle(state, md5blk(s.substring(i - 64, i)));
  }

  s = s.substring(i - 64);
  const tail = new Array(16).fill(0);

  for (i = 0; i < s.length; i++) {
    tail[i >> 2] |= s.charCodeAt(i) << ((i % 4) << 3);
  }

  tail[i >> 2] |= 0x80 << ((i % 4) << 3);

  if (i > 55) {
    md5cycle(state, tail);
    for (i = 0; i < 16; i++) tail[i] = 0;
  }

  tail[14] = n * 8;
  md5cycle(state, tail);
  return state;
}

function rhex(n: number) {
  const hexChr = "0123456789abcdef";
  let s = "";
  for (let j = 0; j < 4; j++) {
    s +=
      hexChr.charAt((n >> (j * 8 + 4)) & 0x0f) +
      hexChr.charAt((n >> (j * 8)) & 0x0f);
  }
  return s;
}

function md5(s: string) {
  return md51(unescape(encodeURIComponent(s))).map(rhex).join("");
}

async function parseJsonResponse(res: Response) {
  const data = await res.json().catch(() => null);

  if (!res.ok) {
    throw new Error(data?.error || data?.message || `Request failed (${res.status})`);
  }

  return data;
}

// ----------------- existing helpers -----------------

export function getGravatarUrl(from: string, size = 80) {
  const email = extractEmailAddress(from);
  if (!email) return null;
  const hash = md5(email.trim().toLowerCase());
  return `https://www.gravatar.com/avatar/${hash}?s=${size}&d=404`;
}

// Gmail (remote) emails
export async function fetchEmails(query: string): Promise<GmailEmail[]> {
  const res = await fetch(
    `${API}/list_emails?max_results=50&q=${encodeURIComponent(query)}`,
    { credentials: "include" },
  );

  const data = await parseJsonResponse(res);

  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.emails)) return data.emails;
  return [];
}

export async function fetchEmailDetail(id: string): Promise<GmailEmailDetail> {
  if (!id?.trim()) {
    throw new Error("Email ID is required");
  }

  const safeId = encodeURIComponent(id);
  const res = await fetch(`${API}/get_email/${safeId}`, {
    credentials: "include",
  });

  const data = await parseJsonResponse(res);
  const email = data?.email ?? data;

  if (!email || typeof email !== "object") {
    throw new Error("Invalid email detail response");
  }

  return {
    id: String(email.id ?? ""),
    subject: String(email.subject ?? ""),
    from: String(email.from ?? ""),
    date: String(email.date ?? ""),
    body: String(email.body ?? email.plain_body ?? email.snippet ?? ""),
    to: typeof email.to === "string" ? email.to : undefined,
    cc: typeof email.cc === "string" ? email.cc : undefined,
    snippet: typeof email.snippet === "string" ? email.snippet : undefined,
    labelIds: Array.isArray(email.labelIds) ? email.labelIds : undefined,
    plain_body: typeof email.plain_body === "string" ? email.plain_body : undefined,
    html_body: typeof email.html_body === "string" ? email.html_body : undefined,
  };
}

// Move a Gmail message to Trash (recoverable in Gmail for 30 days)
export async function trashEmail(id: string) {
  const res = await fetch(`${API}/trash_email/${encodeURIComponent(id)}`, {
    method: "POST",
    credentials: "include",
  });

  return parseJsonResponse(res);
}

// Per-account preferences (display, theme, notifications)
export async function fetchSettings(): Promise<Settings> {
  const res = await fetch(`${API}/settings`, { credentials: "include" });
  const data = await parseJsonResponse(res);

  return { ...DEFAULT_SETTINGS, ...data?.settings } as Settings;
}

export async function saveSettings(settings: Settings): Promise<Settings> {
  const res = await fetch(`${API}/settings`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });

  const data = await parseJsonResponse(res);
  return { ...DEFAULT_SETTINGS, ...data?.settings } as Settings;
}

// Gmail labels, for the sidebar tag list
export async function fetchLabels(): Promise<GmailLabel[]> {
  const res = await fetch(`${API}/list_labels`, { credentials: "include" });
  const data = await parseJsonResponse(res);

  if (Array.isArray(data?.labels)) return data.labels;
  if (Array.isArray(data)) return data;
  return [];
}

// AI summary of an email body
export async function summarizeEmail(
  content: string,
  type: "brief" | "detailed" = "brief",
): Promise<string> {
  const res = await fetch(`${API}/summarize_email`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, type }),
  });

  const data = await parseJsonResponse(res);
  return String(data?.summary ?? "");
}

// Send via Gmail (and backend stores to Postgres)
export async function sendEmailRequest({
  to,
  subject,
  body,
  attachments,
}: {
  to: string;
  subject: string;
  body: string;
  attachments: File[];
}) {
  const formData = new FormData();
  formData.append("to", to.trim());
  formData.append("subject", subject);
  formData.append("body", body);
  attachments.forEach((f) => formData.append("attachments", f));

  const res = await fetch(`${API}/send_email`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });

  return parseJsonResponse(res);
}

// ----------------- DB-backed emails, drafts, schedules & folders -----------------

// Create a Gmail draft; the backend mirrors it into Postgres
export async function createDraftRequest({
  to,
  subject,
  body,
}: {
  to: string;
  subject: string;
  body: string;
}) {
  const res = await fetch(`${API}/create_draft`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, subject, body }),
  });

  return parseJsonResponse(res);
}

// Edit a stored draft, or move a stored email into a folder
export async function updateStoredEmail(
  id: number,
  patch: Partial<Pick<StoredEmail, "subject" | "body" | "to_address" | "folder_id">>,
): Promise<StoredEmail> {
  const res = await fetch(`${API}/stored_emails/${id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });

  return parseJsonResponse(res);
}

export async function deleteStoredEmail(id: number) {
  const res = await fetch(`${API}/stored_emails/${id}`, {
    method: "DELETE",
    credentials: "include",
  });

  return parseJsonResponse(res);
}

export async function fetchScheduledEmails(): Promise<ScheduledRecord[]> {
  const res = await fetch(`${API}/scheduled_emails`, { credentials: "include" });
  const data = await parseJsonResponse(res);

  if (Array.isArray(data?.scheduled)) return data.scheduled;
  if (Array.isArray(data)) return data;
  return [];
}

export async function createScheduledEmail({
  to,
  subject,
  body,
  scheduledFor,
}: {
  to: string;
  subject: string;
  body: string;
  scheduledFor: string;
}): Promise<ScheduledRecord> {
  const res = await fetch(`${API}/scheduled_emails`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, subject, body, scheduled_for: scheduledFor }),
  });

  return parseJsonResponse(res);
}

/** `sent` marks the schedule fulfilled; otherwise it is cancelled and removed. */
export async function deleteScheduledEmail(id: number, sent = false) {
  const res = await fetch(
    `${API}/scheduled_emails/${id}${sent ? "?sent=true" : ""}`,
    { method: "DELETE", credentials: "include" },
  );

  return parseJsonResponse(res);
}

// Fetch emails stored in Postgres (generated/drafts/sent)
export async function fetchStoredEmails(params?: {
  is_draft?: boolean;
  folder_id?: number;
}): Promise<StoredEmail[]> {
  const searchParams = new URLSearchParams();

  if (typeof params?.is_draft === "boolean") {
    searchParams.set("is_draft", params.is_draft ? "true" : "false");
  }
  if (typeof params?.folder_id === "number") {
    searchParams.set("folder_id", String(params.folder_id));
  }

  const queryString = searchParams.toString();
  const url = queryString ? `${API}/stored_emails?${queryString}` : `${API}/stored_emails`;

  const res = await fetch(url, {
    credentials: "include",
  });

  const data = await parseJsonResponse(res);

  if (Array.isArray(data?.emails)) return data.emails;
  if (Array.isArray(data)) return data;
  return [];
}

// Fetch folders from Postgres
export async function fetchFolders(): Promise<DbFolder[]> {
  const res = await fetch(`${API}/folders`, {
    credentials: "include",
  });

  const data = await parseJsonResponse(res);

  if (Array.isArray(data?.folders)) return data.folders;
  if (Array.isArray(data)) return data;
  return [];
}

// Create folder in Postgres
export async function createFolder({
  name,
  description,
}: {
  name: string;
  description?: string;
}): Promise<DbFolder> {
  const res = await fetch(`${API}/folders`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, description }),
  });

  return parseJsonResponse(res);
}