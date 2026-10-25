import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Applications · Job Matcher" };

export default function ApplicationsPage() {
  return (
    <section>
      <PageHeader title="Applications" aside="Drag cards between stages" />
      <ComingSoon phase={7}>
        Jobs you save or apply to show up here as a board: Saved, Applied, Interviewing, Offer,
        Rejected / Withdrawn.
      </ComingSoon>
    </section>
  );
}
