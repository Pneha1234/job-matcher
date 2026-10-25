import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Jobs · Job Matcher" };

export default function JobsPage() {
  return (
    <section>
      <PageHeader title="Jobs" aside="No profile yet" />
      <ComingSoon phase={2}>
        No jobs yet. Set up your profile, then the first source will start filling this list.
      </ComingSoon>
    </section>
  );
}
