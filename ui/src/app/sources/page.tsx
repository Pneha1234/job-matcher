import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Sources · Job Matcher" };

export default function SourcesPage() {
  return (
    <section>
      <PageHeader title="Sources" />
      <ComingSoon phase={2}>
        Health, last run, jobs found and budget used for every free source, with run now and
        pause.
      </ComingSoon>
    </section>
  );
}
