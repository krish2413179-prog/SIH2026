import type { Metadata } from 'next';
import './globals.css';
import { Providers } from '@/components/Providers';

export const metadata: Metadata = {
  title: 'VASP Attribution Engine',
  description: 'Blockchain Intelligence & VASP Attribution Engine for LEA Investigations',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 font-cantata antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
