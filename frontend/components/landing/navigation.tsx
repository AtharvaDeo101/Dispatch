"use client";

import { useState, useEffect } from "react";
import { Menu, X } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

const playfair = "'Playfair Display', Georgia, serif";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:5000";

export function Navigation() {
  const [isScrolled, setIsScrolled] = useState(false);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);

  useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 20);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const checkAuth = async () => {
      setCheckingAuth(true);
      try {
        const res = await fetch(`${API}/me`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setIsAuthenticated("emailAddress" in data);
        } else {
          setIsAuthenticated(false);
        }
      } catch {
        setIsAuthenticated(false);
      } finally {
        setCheckingAuth(false);
      }
    };
    checkAuth();
  }, []);

  const handleLogout = async () => {
    try {
      await fetch(`${API}/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // silently fail
    } finally {
      setIsAuthenticated(false);
      window.location.href = "/";
    }
  };

  const topTextColor = isScrolled ? "hsl(var(--foreground))" : "#ffffff";
  const topMutedTextColor = isScrolled
    ? "hsl(var(--foreground) / 0.72)"
    : "rgba(255,255,255,0.88)";
  const topBorderColor = isScrolled
    ? "hsl(var(--foreground) / 0.2)"
    : "rgba(255,255,255,0.28)";
  const topHoverBg = isScrolled
    ? "hsl(var(--foreground) / 0.05)"
    : "rgba(255,255,255,0.08)";

  return (
    <header
      className={`fixed z-50 transition-all duration-500 ${
        isScrolled ? "top-4 left-4 right-4" : "top-0 left-0 right-0"
      }`}
    >
      <nav
        className={`mx-auto transition-all duration-500 ${
          isScrolled || isMobileMenuOpen
            ? "bg-background/80 backdrop-blur-xl border border-foreground/10 rounded-2xl shadow-lg max-w-[1200px]"
            : "bg-transparent max-w-[1400px]"
        }`}
      >
        <div
          className={`flex items-center justify-between transition-all duration-500 px-6 lg:px-8 ${
            isScrolled ? "h-14" : "h-20"
          }`}
        >
          {/* Logo */}
          <a
            href="/"
            style={{
              fontFamily: playfair,
              fontStyle: "italic",
              fontWeight: 500,
              letterSpacing: "-0.03em",
              lineHeight: 1,
              color: topTextColor,
              fontSize: isScrolled ? "1.2rem" : "1.5rem",
              transition: "font-size 0.5s ease, color 0.3s ease",
              textDecoration: "none",
            }}
          >
            Dispatch
          </a>



          {/* Desktop right actions */}
          <div className="hidden md:flex items-center gap-3">
            <ThemeToggle isScrolled={isScrolled} />

            {checkingAuth ? (
              <div
                className="w-28 h-9 rounded-full animate-pulse"
                style={{
                  background: isScrolled
                    ? "hsl(var(--foreground) / 0.1)"
                    : "rgba(255,255,255,0.16)",
                }}
              />
            ) : isAuthenticated ? (
              <button
                onClick={handleLogout}
                className="rounded-full transition-all duration-300"
                style={{
                  fontFamily: playfair,
                  fontStyle: "italic",
                  fontWeight: 400,
                  fontSize: isScrolled ? "0.75rem" : "0.875rem",
                  color: topMutedTextColor,
                  padding: isScrolled ? "0.3rem 1rem" : "0.45rem 1.25rem",
                  letterSpacing: "0.01em",
                  transition: "all 0.3s ease",
                  background: "transparent",
                  cursor: "pointer",
                  border: `1px solid ${topBorderColor}`,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = topHoverBg;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                Sign out
              </button>
            ) : (
              <a
                href="/login"
                className="rounded-full transition-all duration-300 hover:opacity-85"
                style={{
                  fontFamily: playfair,
                  fontStyle: "italic",
                  fontWeight: 500,
                  fontSize: isScrolled ? "0.75rem" : "0.875rem",
                  color: isScrolled ? "hsl(var(--primary-foreground))" : "#ffffff",
                  background: isScrolled
                    ? "hsl(var(--primary))"
                    : "rgba(255,255,255,0.12)",
                  border: isScrolled
                    ? "1px solid transparent"
                    : "1px solid rgba(255,255,255,0.24)",
                  padding: isScrolled ? "0.3rem 1rem" : "0.45rem 1.5rem",
                  letterSpacing: "-0.01em",
                  textDecoration: "none",
                  display: "inline-block",
                  transition: "all 0.3s ease",
                  backdropFilter: isScrolled ? "none" : "blur(8px)",
                }}
              >
                Get Started
              </a>
            )}
          </div>

          {/* Mobile right actions */}
          <div className="flex md:hidden items-center gap-2">
            <ThemeToggle isScrolled={isScrolled} />
            <button
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="p-2 transition-colors duration-300"
              aria-label="Toggle menu"
              style={{ color: topTextColor }}
            >
              {isMobileMenuOpen ? (
                <X className="w-6 h-6" />
              ) : (
                <Menu className="w-6 h-6" />
              )}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        <div
          className={`md:hidden fixed inset-0 bg-background z-40 transition-all duration-500 ${
            isMobileMenuOpen
              ? "opacity-100 pointer-events-auto"
              : "opacity-0 pointer-events-none"
          }`}
          style={{ top: 0 }}
        >
          <div className="flex flex-col h-full px-8 pt-28 pb-8">
            <div
              className={`flex flex-col gap-6 transition-all duration-500 ${
                isMobileMenuOpen
                  ? "opacity-100 translate-y-0"
                  : "opacity-0 translate-y-4"
              }`}
            >

            </div>

            <div
              className={`flex gap-4 pt-8 border-t border-foreground/10 mt-auto transition-all duration-500 ${
                isMobileMenuOpen
                  ? "opacity-100 translate-y-0"
                  : "opacity-0 translate-y-4"
              }`}
              style={{ transitionDelay: isMobileMenuOpen ? "300ms" : "0ms" }}
            >
              {isAuthenticated ? (
                <button
                  onClick={handleLogout}
                  className="flex-1 flex items-center justify-center rounded-full border border-foreground/20 transition-all duration-300 hover:bg-foreground/5"
                  style={{
                    fontFamily: playfair,
                    fontStyle: "italic",
                    fontWeight: 400,
                    fontSize: "1rem",
                    color: "hsl(var(--foreground))",
                    height: "3.5rem",
                    letterSpacing: "0.01em",
                    background: "transparent",
                    cursor: "pointer",
                  }}
                >
                  Sign out
                </button>
              ) : (
                <a
                  href="/login"
                  onClick={() => setIsMobileMenuOpen(false)}
                  className="flex-1 flex items-center justify-center rounded-full transition-all duration-300 hover:opacity-85"
                  style={{
                    fontFamily: playfair,
                    fontStyle: "italic",
                    fontWeight: 500,
                    fontSize: "1rem",
                    color: "hsl(var(--primary-foreground))",
                    background: "hsl(var(--primary))",
                    height: "3.5rem",
                    textDecoration: "none",
                    letterSpacing: "-0.01em",
                  }}
                >
                  Get Started
                </a>
              )}
            </div>
          </div>
        </div>
      </nav>
    </header>
  );
}