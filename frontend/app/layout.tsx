import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const jetbrainsMono = JetBrains_Mono({ 
  subsets: ['latin'], 
  variable: '--font-mono',
  display: 'swap' 
});

export const metadata = {
  title: 'Eepy Host | Cozy MCP Hosting',
  description: 'Stay cozy while your AI context does the hard work.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${jetbrainsMono.variable} bg-void text-white antialiased`}>
        {children}
      </body>
    </html>
  );
}
