"use client"

import { Button } from "@/components/ui/button"
import Image from "next/image"

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api"

export default function LoginPage() {
  const handleGoogleLogin = () => {
    window.location.href = `${API_BASE_URL}/login`
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-background">
      {/* Background video */}
      <div className="absolute inset-0 z-0">
        <video
          autoPlay
          muted
          loop
          playsInline
          className="h-full w-full object-cover object-center"
        >
          <source src="/login1.mp4" type="video/mp4" />
        </video>

        <div className="absolute inset-0 bg-black/35" />
      </div>

      {/* Foreground */}
      <div className="relative z-20 flex min-h-screen items-center justify-center px-6 py-8 lg:px-10">
        <div className="grid w-full max-w-6xl min-h-[700px] overflow-hidden rounded-2xl border border-white/10 shadow-2xl lg:grid-cols-[1.1fr_0.9fr]">
          
          {/* Left panel — black background */}
          <div className="flex items-center justify-center bg-black/78 p-8 sm:p-10 lg:p-14">
            <div className="w-full max-w-md">
              <div className="mb-10">
                <p className="mb-3 text-xs uppercase tracking-[0.22em] text-white/45">
                  Secure access
                </p>
                <h1 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl">
                  Welcome back to Dispatch
                </h1>
                <p className="mt-4 max-w-sm text-sm leading-6 text-white/65">
                  Sign in with your Google account to continue to Dispatch and manage your email workflow with clarity.
                </p>
              </div>

              <Button
                className="h-12 w-full border-white/15 bg-white text-black hover:bg-white/90"
                variant="outline"
                onClick={handleGoogleLogin}
              >
                <svg className="mr-3 h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    fill="#4285F4"
                    d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                  />
                </svg>
                Continue with Google
              </Button>

              <p className="mt-6 text-center text-xs leading-5 text-white/40">
                By continuing, you allow Dispatch to access Gmail for reading and sending emails on your behalf.
              </p>
            </div>
          </div>

          {/* Right panel — transparent with logo only */}
          <div className="relative hidden lg:flex items-center justify-center bg-transparent p-10">
            <div className="flex flex-col items-center justify-center rounded-xl border border-white/10 bg-white/5 p-6 backdrop-blur-sm">
              <Image
                src="/icon.png"
                alt="Dispatch Logo"
                width={220}
                height={220}
                className="mx-auto"
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}