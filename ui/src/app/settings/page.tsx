import { ComingSoon, PageHeader } from "@/components/page-header";

export const metadata = { title: "Settings · Job Matcher" };

export default function SettingsPage() {
  return (
    <section>
      <PageHeader title="Settings" />
      <ComingSoon phase={7}>
        Match weights, saved searches, target countries, schedules, model, currency and
        notifications.
      </ComingSoon>
    </section>
  );
}
