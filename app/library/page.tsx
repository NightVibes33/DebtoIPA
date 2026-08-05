import type { Metadata } from 'next';
import DebLibraryApp from '@/components/DebLibraryApp';

export const metadata: Metadata = {
  title: 'DEB Library — DebToIPA',
  description: 'Browse public iOS DEB repositories and load eligible packages into the DebToIPA conversion builder.',
};

export default function LibraryPage() {
  return <DebLibraryApp />;
}
