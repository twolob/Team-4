import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { useState, type FormEvent } from "react"
import { toast } from "sonner"

import { AuthLayout } from "@/components/Common/AuthLayout"
import { Input } from "@/components/ui/input"
import { LoadingButton } from "@/components/ui/loading-button"
import { PasswordInput } from "@/components/ui/password-input"
import useAuth, { isLoggedIn } from "@/hooks/useAuth"
import { apiBaseUrl, liberianPhone } from "@/lib/agtrack"

const counties = [
  "Bomi",
  "Bong",
  "Gbarpolu",
  "Grand Bassa",
  "Grand Cape Mount",
  "Grand Gedeh",
  "Grand Kru",
  "Lofa",
  "Margibi",
  "Maryland",
  "Montserrado",
  "Nimba",
  "River Cess",
  "River Gee",
  "Sinoe",
]
const farmTypes = [
  "Rice",
  "Cassava",
  "Vegetables",
  "Cocoa",
  "Rubber",
  "Oil Palm",
  "Livestock",
  "Mixed",
]

export const Route = createFileRoute("/register-farmer")({
  beforeLoad: () => {
    if (isLoggedIn()) throw redirect({ to: "/dashboard" })
  },
  component: RegisterFarmer,
  head: () => ({ meta: [{ title: "Register as a farmer | AgTrack" }] }),
})

function RegisterFarmer() {
  const { loginMutation } = useAuth()
  const [pending, setPending] = useState(false)
  const [registered, setRegistered] = useState(false)
  const [error, setError] = useState("")

  async function register(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending || registered) return

    const fields = new FormData(event.currentTarget)
    const phone = String(fields.get("phone")).replace(/[\s()-]/g, "")
    const name = String(fields.get("name")).trim()
    const password = String(fields.get("password"))
    if (!name || !liberianPhone(phone)) {
      setError(
        "Enter your name and a Liberian phone number starting with +231.",
      )
      return
    }

    setPending(true)
    setError("")
    try {
      const response = await fetch(`${apiBaseUrl}/api/v1/farmers/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: name,
          phone_number: phone,
          password,
          farm: {
            name,
            county: fields.get("county"),
            farm_type: fields.get("farm_type"),
          },
        }),
      })
      if (!response.ok) {
        const body = await response.json().catch(() => null)
        throw new Error(
          typeof body?.detail === "string"
            ? body.detail
            : "Registration failed. Check your details and try again.",
        )
      }
      setRegistered(true)
      toast.success("Your AgTrack account is ready.")
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Registration is temporarily unavailable.",
      )
      setPending(false)
      return
    }

    try {
      await loginMutation.mutateAsync({ username: phone, password })
    } catch {
      setError("Your account was created. Sign in to open your dashboard.")
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout>
      <form onSubmit={register} className="grid gap-4">
        <h1 className="text-2xl font-bold">Register as a farmer</h1>
        <label className="grid gap-2 text-sm font-medium">
          Full name
          <Input name="name" autoComplete="name" maxLength={255} required />
        </label>
        <label className="grid gap-2 text-sm font-medium">
          Phone number
          <Input
            name="phone"
            type="tel"
            autoComplete="tel"
            placeholder="+231"
            required
          />
        </label>
        <label className="grid gap-2 text-sm font-medium">
          County
          <select
            name="county"
            required
            defaultValue=""
            className="h-9 rounded-md border bg-background px-3"
          >
            <option value="" disabled>
              Select your county
            </option>
            {counties.map((county) => (
              <option key={county}>{county}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-medium">
          Farm type
          <select
            name="farm_type"
            required
            defaultValue=""
            className="h-9 rounded-md border bg-background px-3"
          >
            <option value="" disabled>
              Select a farm type
            </option>
            {farmTypes.map((farmType) => (
              <option key={farmType}>{farmType}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm font-medium">
          Password
          <PasswordInput
            name="password"
            autoComplete="new-password"
            minLength={8}
            maxLength={128}
            required
          />
        </label>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <LoadingButton type="submit" loading={pending} disabled={registered}>
          Create account
        </LoadingButton>
        <p className="text-sm">
          Already registered?{" "}
          <Link to="/login" className="underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthLayout>
  )
}
