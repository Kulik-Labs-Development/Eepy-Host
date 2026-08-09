import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Eepy Host | Cozy MCP Hosting',
  description: 'Stay cozy while your AI context does the hard work.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-void text-white antialiased">{children}</body>
    </html>
  )
}
