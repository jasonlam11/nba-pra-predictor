import type { Metadata } from "next";
import "./globals.css";
import Header from "@/components/Header";

export const metadata: Metadata = {
  title: "NBA PRA Predictor",
  description: "ML-powered NBA player stat predictions",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-court text-chalk antialiased" suppressHydrationWarning>
        {/* Noise texture overlay */}
        <div className="court-texture fixed inset-0 pointer-events-none z-0" />

        {/* Main content */}
        <div className="relative z-10">
          <Header />
          {children}
        </div>
      </body>
    </html>
  );
}