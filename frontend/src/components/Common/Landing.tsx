import { Link } from "@tanstack/react-router"
import { ArrowRight, Leaf, Search } from "lucide-react"
import { type FormEvent, useState } from "react"
import { apiBaseUrl } from "@/lib/agtrack"

type BatchHistory = {
  batch_code: string
  crop: string
  county: string
  stages: { status: keyof typeof stageLabels; recorded_at: string }[]
}

const stageLabels = {
  HARVESTED: "Harvested",
  STORED: "Stored",
  IN_TRANSIT: "In transit",
  DELIVERED: "Delivered",
}

const features = [
  ["Traceability", "Follow a batch from harvest to delivery."],
  ["Inventory & expenses", "Track stock movements and farm spending."],
  ["Loss records", "Keep a record of what was lost and why."],
  ["Reports", "Summarize what your farm harvested, spent, and lost."],
]

function BatchLookup() {
  const [code, setCode] = useState(
    new URLSearchParams(window.location.search).get("batch") ?? "",
  )
  const [history, setHistory] = useState<BatchHistory | null>(null)
  const [message, setMessage] = useState("")
  const [pending, setPending] = useState(false)

  async function lookup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const batchCode = code.trim()
    if (pending || !batchCode) return

    setPending(true)
    setHistory(null)
    setMessage("")
    try {
      const response = await fetch(
        `${apiBaseUrl}/api/v1/public/batches/${encodeURIComponent(batchCode)}`,
      )
      if (response.status === 404) {
        setMessage("No batch found. Check the code and try again.")
      } else if (response.ok) {
        setHistory(await response.json())
      } else {
        throw new Error("Batch lookup failed")
      }
    } catch {
      setMessage("Batch lookup is temporarily unavailable. Please try again.")
    } finally {
      setPending(false)
    }
  }

  return (
    <section id="lookup" className="mx-auto max-w-4xl scroll-mt-24 px-5 py-16">
      <div className="rounded-3xl border border-green-200 bg-white p-6 sm:p-10">
        <h2 className="text-3xl font-bold">Check a produce batch</h2>
        <form onSubmit={lookup} className="mt-5">
          <label htmlFor="batch-code" className="text-sm font-semibold">
            Batch code
          </label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input
              id="batch-code"
              className="min-w-0 flex-1 rounded-xl border border-green-300 bg-white px-4 py-3"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              maxLength={100}
              required
            />
            <button
              type="submit"
              disabled={pending || !code.trim()}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#2e7d32] px-5 py-3 font-semibold text-white disabled:opacity-65"
            >
              <Search size={18} aria-hidden />
              Look up
            </button>
          </div>
        </form>
        <p role="status" className="mt-3 text-sm text-green-900">
          {pending ? "Looking up the batch…" : message}
        </p>
        {history && (
          <div className="mt-4" aria-live="polite">
            <h3 className="text-xl font-semibold">
              {history.crop} · {history.county}
            </h3>
            <p className="mt-1 break-all text-sm text-green-900">
              {history.batch_code}
            </p>
            <ol className="mt-4 space-y-3 border-l-2 border-lime-500 pl-4">
              {history.stages.map((stage, index) => (
                <li
                  key={`${stage.recorded_at}-${index}`}
                  className="flex flex-wrap justify-between gap-2"
                >
                  <span className="font-medium">
                    {stageLabels[stage.status]}
                  </span>
                  <time dateTime={stage.recorded_at}>
                    {new Intl.DateTimeFormat("en-LR", {
                      dateStyle: "medium",
                      timeZone: "Africa/Monrovia",
                    }).format(new Date(stage.recorded_at))}
                  </time>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </section>
  )
}

export function Landing() {
  return (
    <div className="min-h-screen bg-[#f7faf3] text-[#18311c]">
      <header className="border-b border-green-100 bg-white">
        <nav
          aria-label="Main navigation"
          className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-4"
        >
          <Link to="/" className="flex items-center gap-2 text-xl font-bold">
            <img
              src="/assets/images/agtrack.png"
              alt=""
              width="36"
              height="36"
            />
            AgTrack
          </Link>
          <div className="flex flex-wrap items-center gap-4 text-sm font-semibold">
            <a href="#about">About</a>
            <a href="#faq">FAQs</a>
            <Link to="/login">Sign in</Link>
            <Link
              to="/register-farmer"
              className="rounded-full bg-[#2e7d32] px-4 py-2 text-white"
            >
              Sign up
            </Link>
          </div>
        </nav>
      </header>
      <main>
        <section className="bg-linear-to-br from-lime-100 via-[#f7faf3] to-green-100">
          <div className="mx-auto max-w-6xl px-5 py-20 sm:py-28">
            <h1 className="max-w-3xl text-5xl font-bold tracking-tight sm:text-7xl">
              Keep farm records. Trace your harvest.
            </h1>
            <p className="mt-5 max-w-xl text-lg text-green-900">
              AgTrack helps Liberian farmers keep track of harvests, costs, and
              losses. Buyers can check the history of a produce batch.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/register-farmer"
                className="inline-flex items-center gap-2 rounded-xl bg-[#2e7d32] px-5 py-3 font-semibold text-white"
              >
                Get started <ArrowRight size={18} aria-hidden />
              </Link>
              <a
                href="#lookup"
                className="rounded-xl border border-[#2e7d32] px-5 py-3 font-semibold"
              >
                Check a batch
              </a>
            </div>
          </div>
        </section>
        <section id="about" className="mx-auto max-w-6xl px-5 pt-16">
          <h2 className="text-3xl font-bold">About AgTrack</h2>
          <p className="mt-3 max-w-2xl">
            AgTrack gives smallholder farmers in Liberia one place to keep farm
            records and share batch history with buyers.
          </p>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {features.map(([title, description]) => (
              <article
                key={title}
                className="rounded-2xl border border-green-100 bg-white p-5"
              >
                <Leaf size={22} className="text-[#2e7d32]" aria-hidden />
                <h3 className="mt-3 font-bold">{title}</h3>
                <p className="mt-1 text-sm text-green-900">{description}</p>
              </article>
            ))}
          </div>
        </section>
        <BatchLookup />
        <section id="faq" className="mx-auto max-w-4xl px-5 pb-16">
          <h2 className="text-3xl font-bold">Frequently asked questions</h2>
          <details className="mt-4 rounded-xl border border-green-100 bg-white p-4">
            <summary className="cursor-pointer font-semibold">
              Do buyers need an account?
            </summary>
            <p className="mt-2">
              Anyone with a batch code can check its history on this page.
            </p>
          </details>
          <details className="mt-3 rounded-xl border border-green-100 bg-white p-4">
            <summary className="cursor-pointer font-semibold">
              What can buyers see?
            </summary>
            <p className="mt-2">
              The result shows the crop, county, and dates of recorded batch
              stages.
            </p>
          </details>
        </section>
      </main>
      <footer className="border-t border-green-100 bg-white px-5 py-6 text-center text-sm">
        AgTrack · Farm records for Liberia
      </footer>
    </div>
  )
}
