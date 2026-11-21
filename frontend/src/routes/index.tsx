import { createFileRoute } from "@tanstack/react-router"

import { Landing } from "@/components/Common/Landing"

export const Route = createFileRoute("/")({
  component: Landing,
  head: () => ({
    meta: [{ title: "AgTrack | Farm records and traceability" }],
  }),
})
