import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useEffect } from 'react';
import { MotionConfig } from 'motion/react';
import Nav from './components/Nav.jsx';
import Landing from './routes/Landing.jsx';
import Explorer from './routes/Explorer.jsx';
import Rankings from './routes/Rankings.jsx';
import Statistics from './routes/Statistics.jsx';
import { SPRING } from './lib/motion.js';
import { DataProvider } from './data/DataContext.jsx';
import { FiltersProvider } from './data/FiltersContext.jsx';
import { DATA_CONFIG } from './config/dataSource.js';

/** Route changes start the new screen at the top, as a page load would. */
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

export default function App() {
  return (
    /*
      `reducedMotion="user"` makes every Motion component in the tree respect
      the operating system setting, so transform and layout animations are
      disabled at the library level rather than component by component.
    */
    <MotionConfig reducedMotion="user" transition={SPRING}>
      {/* One data source and one filter state for every screen (src/config/dataSource.js). */}
      <DataProvider config={DATA_CONFIG}>
        <FiltersProvider>
          <ScrollToTop />
          <Nav />
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/explorer" element={<Explorer />} />
            <Route path="/rankings" element={<Rankings />} />
            <Route path="/statistics" element={<Statistics />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </FiltersProvider>
      </DataProvider>
    </MotionConfig>
  );
}
