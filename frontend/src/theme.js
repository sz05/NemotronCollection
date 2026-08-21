import { createTheme } from '@mui/material/styles'

// Clean, professional dark theme: neutral near-black surfaces, restrained
// hairline borders, one muted blue accent, and flat (non-gradient) components.
// Deliberately understated -- no glows or gradient text.
const ACCENT = '#4b7bec'

const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: ACCENT },
    secondary: { main: '#9b9ca3' },
    success: { main: '#3fb950' },
    error: { main: '#e5534b' },
    warning: { main: '#d29922' },
    info: { main: ACCENT },
    background: { default: '#1e1f22', paper: '#242529' },
    divider: 'rgba(255, 255, 255, 0.09)',
    text: { primary: '#ececf1', secondary: '#9b9ca3' },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily:
      "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    h4: { fontWeight: 600, letterSpacing: '-0.01em' },
    h5: { fontWeight: 600 },
    subtitle1: { fontWeight: 600 },
    button: { fontWeight: 500, textTransform: 'none' },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        '*::-webkit-scrollbar': { width: 10, height: 10 },
        '*::-webkit-scrollbar-thumb': {
          background: 'rgba(255, 255, 255, 0.14)',
          borderRadius: 8,
          border: '2px solid transparent',
          backgroundClip: 'padding-box',
        },
        '*::-webkit-scrollbar-thumb:hover': {
          background: 'rgba(255, 255, 255, 0.22)',
          backgroundClip: 'padding-box',
        },
        '*::-webkit-scrollbar-track': { background: 'transparent' },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#242529',
          border: '1px solid rgba(255, 255, 255, 0.09)',
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 8, paddingInline: 14 },
        outlined: { borderColor: 'rgba(255, 255, 255, 0.16)' },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 12,
          border: '1px solid rgba(255, 255, 255, 0.1)',
          backgroundImage: 'none',
          boxShadow: '0 16px 48px -16px rgba(0, 0, 0, 0.7)',
        },
      },
    },
    MuiBackdrop: {
      styleOverrides: { root: { backgroundColor: 'rgba(0, 0, 0, 0.55)' } },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: 'rgba(255, 255, 255, 0.07)' },
        head: {
          color: '#9b9ca3',
          fontWeight: 600,
          fontSize: '0.72rem',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
        },
      },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
    MuiOutlinedInput: { styleOverrides: { root: { borderRadius: 8 } } },
    MuiListItemButton: { styleOverrides: { root: { borderRadius: 8 } } },
  },
})

export default theme
