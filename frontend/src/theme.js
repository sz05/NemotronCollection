import { createTheme } from '@mui/material/styles'

// Dark theme roughly matching the existing App.css palette:
// #1e1e1e / #232323 surfaces, #333 borders, blue accents (#24304a / #7ab8ff),
// and the status greens/reds/ambers used across the plain-CSS components.
const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: '#7ab8ff' },
    secondary: { main: '#e6a817' },
    success: { main: '#4caf50' },
    error: { main: '#f44336' },
    warning: { main: '#e6a817' },
    background: {
      default: '#181818',
      paper: '#1e1e1e',
    },
    divider: '#333',
    text: {
      primary: '#f0f0f0',
      secondary: '#888',
    },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily:
      'system-ui, Avenir, Helvetica, Arial, sans-serif',
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: { backgroundImage: 'none' },
      },
    },
  },
})

export default theme
