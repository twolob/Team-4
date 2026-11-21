import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import { useState } from "react"

import { client } from "@/client/client.gen"
import useAuth from "@/hooks/useAuth"

type Farm = { id: string; name: string; county: string; farm_type: string }
type Overview = {
  inventory_item_count: number
  expenses: { currency: string; amount: string }[]
  harvests: { crop_name: string; quantity: string; unit: string }[]
  losses: {
    loss_type: string
    crop_name: string | null
    quantity: string
    unit: string
  }[]
}

export const Route = createFileRoute("/_layout/dashboard")({
  component: Dashboard,
  head: () => ({
    meta: [{ title: "AgTrack | Farm overview" }],
  }),
})

function Dashboard() {
  const { user } = useAuth()
  const [selectedId, setSelectedId] = useState("")
  const farms = useQuery({
    queryKey: ["farms", user?.id],
    queryFn: async () =>
      (
        await client.get<{ 200: Farm[] }, unknown, true>({
          url: "/api/v1/farms/",
          security: [{ scheme: "bearer", type: "http" }],
          throwOnError: true,
        })
      ).data,
    enabled: !!user,
  })
  const farm =
    farms.data?.find(({ id }) => id === selectedId) ?? farms.data?.[0]
  const overview = useQuery({
    queryKey: ["farm-overview", farm?.id],
    queryFn: async () =>
      (
        await client.get<{ 200: Overview }, unknown, true>({
          url: "/api/v1/farms/{farm_id}/overview",
          path: { farm_id: farm?.id },
          security: [{ scheme: "bearer", type: "http" }],
          throwOnError: true,
        })
      ).data,
    enabled: !!farm,
  })

  return (
    <section className="space-y-5">
      <h1 className="text-2xl font-bold">
        Welcome{user?.full_name ? `, ${user.full_name}` : ""}
      </h1>
      {farms.isFetching && <p role="status">Loading farms…</p>}
      {farms.isError && (
        <p role="alert">
          Could not load your farms.{" "}
          <button
            className="underline"
            type="button"
            onClick={() => farms.refetch()}
          >
            Try again
          </button>
        </p>
      )}
      {farms.data?.length === 0 && (
        <p>No farms are linked to this account yet.</p>
      )}
      {farm && (
        <>
          <label className="grid max-w-xs gap-2 text-sm font-medium">
            Farm
            <select
              value={farm.id}
              onChange={(event) => setSelectedId(event.target.value)}
              className="rounded-md border bg-background p-2"
            >
              {farms.data?.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.name}
                </option>
              ))}
            </select>
          </label>
          <p className="text-muted-foreground">
            {farm.county} · {farm.farm_type}
          </p>
          {overview.isPending && <p role="status">Loading farm overview…</p>}
          {overview.isError && (
            <p role="alert">
              Could not load the overview.{" "}
              <button
                className="underline"
                type="button"
                onClick={() => overview.refetch()}
              >
                Try again
              </button>
            </p>
          )}
          {overview.data && <FarmTotals data={overview.data} />}
        </>
      )}
    </section>
  )
}

function FarmTotals({ data }: { data: Overview }) {
  const cards = [
    { title: "Inventory items", rows: [String(data.inventory_item_count)] },
    {
      title: "Expenses",
      rows: data.expenses.map(
        ({ amount, currency }) => `${currency} ${amount}`,
      ),
    },
    {
      title: "Harvests",
      rows: data.harvests.map(
        ({ crop_name, quantity, unit }) => `${crop_name} · ${quantity} ${unit}`,
      ),
    },
    {
      title: "Losses",
      rows: data.losses.map(
        ({ loss_type, crop_name, quantity, unit }) =>
          `${crop_name ?? loss_type} · ${quantity} ${unit}`,
      ),
    },
  ]

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {cards.map(({ title, rows }) => (
        <article key={title} className="rounded-xl border bg-card p-5">
          <h2 className="font-semibold">{title}</h2>
          {rows.length ? (
            <ul className="mt-2 space-y-1 text-sm">
              {rows.map((row, index) => (
                <li key={`${row}-${index}`}>{row}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              No records yet.
            </p>
          )}
        </article>
      ))}
    </div>
  )
}
