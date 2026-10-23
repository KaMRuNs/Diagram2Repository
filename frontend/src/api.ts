import type { Graph, Health, JobEvent, JobView, LicenseType, Options } from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<Health>(r)),

  samples: () => fetch("/api/samples").then((r) => json<{ name: string; title: string }[]>(r)),

  startSample: (name: string) =>
    fetch(`/api/samples/${encodeURIComponent(name)}`, { method: "POST" }).then((r) =>
      json<{ job_id: string }>(r),
    ),

  upload: (file: File, license: LicenseType, author: string) => {
    const form = new FormData();
    form.append("image", file);
    form.append("license_type", license);
    form.append("author", author);
    return fetch("/api/jobs", { method: "POST", body: form }).then((r) => json<{ job_id: string }>(r));
  },

  job: (id: string) => fetch(`/api/jobs/${id}`).then((r) => json<JobView>(r)),

  regenerate: (id: string, graph: Graph, options: Options, useAgent: boolean) =>
    fetch(`/api/jobs/${id}/graph`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ graph, options, use_agent: useAgent }),
    }).then((r) => json<{ job_id: string }>(r)),

  imageUrl: (id: string) => `/api/jobs/${id}/image`,

  events: (id: string, after: number, onEvent: (e: JobEvent) => void): (() => void) => {
    const es = new EventSource(`/api/jobs/${id}/events?after=${after}`);
    es.onmessage = (msg) => onEvent(JSON.parse(msg.data) as JobEvent);
    return () => es.close();
  },
};
