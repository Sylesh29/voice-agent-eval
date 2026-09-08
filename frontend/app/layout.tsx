import "./globals.css";
import Nav from "./nav";

export const metadata = {
  title: "Kyron Eval",
  description: "Evaluation platform for a healthcare voice agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <div className="wrap">{children}</div>
      </body>
    </html>
  );
}
