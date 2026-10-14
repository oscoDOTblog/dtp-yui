"use client";

import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";

export default function TrackedJobsPage() {
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => { apiGet("/jobs").then(setJobs).catch((e) => setError(e.message)); }, []);
  return <main className="mx-auto max-w-6xl space-y-6 p-8">
    <div><p className="text-sm uppercase tracking-widest text-slate-500">CV2 / tracked jobs</p><h1 className="text-4xl font-semibold">Application command center</h1><p className="mt-2 text-slate-500">Every listing, score, document package, and approval state in one place.</p></div>
    {error && <p className="rounded-lg bg-red-50 p-3 text-red-700">{error}</p>}
    <div className="overflow-hidden rounded-xl border bg-white shadow-sm"><table className="w-full text-left text-sm"><thead className="bg-slate-50 text-slate-500"><tr><th className="p-4">Role</th><th className="p-4">Company</th><th className="p-4">Match</th><th className="p-4">Recommendation</th><th className="p-4">Application</th></tr></thead><tbody>{jobs.map((job) => <tr key={job._id} className="border-t"><td className="p-4 font-medium">{job.title || job.role || "Untitled role"}</td><td className="p-4">{job.company || "—"}</td><td className="p-4">{job.matchScore == null ? "Pending" : `${job.matchScore}%`}</td><td className="p-4 capitalize">{job.recommendation || "—"}</td><td className="p-4 capitalize">{job.applicationStatus || job.status || "new"}</td></tr>)}</tbody></table>{!jobs.length && !error && <p className="p-8 text-center text-slate-500">No jobs tracked yet.</p>}</div>
  </main>;
}
