const DAY = 86_400_000;

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 60_000) return "just now";
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} min ago`;
  if (ms < DAY) return `${Math.floor(ms / 3_600_000)} h ago`;
  const days = Math.floor(ms / DAY);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function postedLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / DAY);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  return `${days} days ago`;
}

export function isToday(iso: string): boolean {
  const d = new Date(iso);
  const now = new Date();
  return d.toDateString() === now.toDateString();
}

const SYMBOL: Record<string, string> = { EUR: "€", USD: "$", GBP: "£", INR: "₹", NPR: "Rs ", CHF: "CHF ", SEK: "SEK ", NOK: "NOK ", CAD: "CA$", AUD: "A$" };

/** Annual amounts; INR and NPR use lakh/crore like Indian and Nepali postings do. */
export function money(amount: number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined) return "";
  const sym = SYMBOL[currency] ?? `${currency} `;
  if (currency === "INR" || currency === "NPR") {
    if (amount >= 10_000_000) return `${sym}${(amount / 10_000_000).toFixed(1).replace(/\.0$/, "")} Cr`;
    return `${sym}${(amount / 100_000).toFixed(1).replace(/\.0$/, "")}L`;
  }
  if (amount >= 1000) return `${sym}${Math.round(amount / 1000)}k`;
  return `${sym}${Math.round(amount)}`;
}

export function salaryRange(min: number | null, max: number | null, currency: string): string {
  if (min === null && max === null) return "";
  if (min !== null && max !== null && Math.round(min) !== Math.round(max)) {
    return `${money(min, currency)}–${money(max, currency).replace(/^[^\d]+/, "")}`;
  }
  return money(max ?? min, currency);
}

export function scoreTone(pct: number | null | undefined): "hi" | "mid" | "lo" {
  if (pct === null || pct === undefined) return "lo";
  return pct >= 80 ? "hi" : pct >= 60 ? "mid" : "lo";
}

export const JOB_TYPE_LABEL: Record<string, string> = {
  "full-time": "Full-time",
  contract: "Contract",
  freelance: "Freelance",
  "part-time": "Part-time",
  internship: "Internship",
};

export const WORK_MODE_LABEL: Record<string, string> = { onsite: "Onsite", hybrid: "Hybrid", remote: "Remote" };

export const STATUS_LABEL: Record<string, string> = {
  saved: "Saved",
  applied: "Applied",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  archived: "",
};

const SOURCE_LABEL: Record<string, string> = {
  jobspy_linkedin: "LinkedIn",
  jobspy_indeed: "Indeed",
  jobspy_glassdoor: "Glassdoor",
  jobspy_google: "Google Jobs",
  jobspy_naukri: "Naukri",
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  workable: "Workable",
  recruitee: "Recruitee",
  personio: "Personio",
  smartrecruiters: "SmartRecruiters",
  workday: "Workday",
  remotive: "Remotive",
  remoteok: "RemoteOK",
  arbeitnow: "Arbeitnow",
  himalayas: "Himalayas",
  jobicy: "Jobicy",
  weworkremotely: "We Work Remotely",
  hn_whos_hiring: "HN Who's Hiring",
  jobtech_se: "JobTech",
  merojob: "Merojob",
  kumarijob: "Kumarijob",
  jobsnepal: "JobsNepal",
  jobejee: "Jobejee",
  shine: "Shine",
  internshala: "Internshala",
  freshersworld: "Freshersworld",
  teamtailor: "Teamtailor",
  adzuna: "Adzuna",
  jooble: "Jooble",
  reed: "Reed",
  usajobs: "USAJobs",
  france_travail: "France Travail",
  company_sites: "Company site",
  manual: "Added by you",
};

export function sourceLabel(name: string): string {
  return SOURCE_LABEL[name] ?? name;
}
