package main

import (
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

// ============================================================================
// Win32 API function pointers (lazy-loaded)
// ============================================================================

var (
	user32   = windows.NewLazySystemDLL("user32.dll")
	gdi32    = windows.NewLazySystemDLL("gdi32.dll")
	shell32  = windows.NewLazySystemDLL("shell32.dll")
	dwmapi   = windows.NewLazySystemDLL("dwmapi.dll")
	kernel32 = windows.NewLazySystemDLL("kernel32.dll")
	gdiplus  = windows.NewLazySystemDLL("gdiplus.dll")
	ole32    = windows.NewLazySystemDLL("ole32.dll")
)

var (
	procRegisterClassExW            = user32.NewProc("RegisterClassExW")
	procCreateWindowExW             = user32.NewProc("CreateWindowExW")
	procDefWindowProcW              = user32.NewProc("DefWindowProcW")
	procGetMessageW                 = user32.NewProc("GetMessageW")
	procTranslateMessage            = user32.NewProc("TranslateMessage")
	procDispatchMessageW            = user32.NewProc("DispatchMessageW")
	procPostQuitMessage             = user32.NewProc("PostQuitMessage")
	procDestroyWindow               = user32.NewProc("DestroyWindow")
	procShowWindow                  = user32.NewProc("ShowWindow")
	procUpdateWindow                = user32.NewProc("UpdateWindow")
	procGetDC                       = user32.NewProc("GetDC")
	procReleaseDC                   = user32.NewProc("ReleaseDC")
	procBeginPaint                  = user32.NewProc("BeginPaint")
	procEndPaint                    = user32.NewProc("EndPaint")
	procSetWindowPos                = user32.NewProc("SetWindowPos")
	procGetCursorPos                = user32.NewProc("GetCursorPos")
	procGetSystemMetrics            = user32.NewProc("GetSystemMetrics")
	procSetWindowRgn                = user32.NewProc("SetWindowRgn")
	procInvalidateRect              = user32.NewProc("InvalidateRect")
	procFillRect                    = user32.NewProc("FillRect")
	procDrawTextW                   = user32.NewProc("DrawTextW")
	procSetBkMode                   = user32.NewProc("SetBkMode")
	procSetTextColor                = user32.NewProc("SetTextColor")
	procCreateSolidBrush            = user32.NewProc("CreateSolidBrush")
	procCreatePen                   = user32.NewProc("CreatePen")
	procSelectObject                = user32.NewProc("SelectObject")
	procDeleteObject                = user32.NewProc("DeleteObject")
	procMoveToEx                    = user32.NewProc("MoveToEx")
	procLineTo                      = user32.NewProc("LineTo")
	procRoundRect                   = user32.NewProc("RoundRect")
	procEllipse                     = user32.NewProc("Ellipse")
	procGetClientRect               = user32.NewProc("GetClientRect")
	procSetForegroundWindow         = user32.NewProc("SetForegroundWindow")
	procSetWindowLongPtrW           = user32.NewProc("SetWindowLongPtrW")
	procGetWindowLongPtrW           = user32.NewProc("GetWindowLongPtrW")
	procSetProcessDPIAware          = user32.NewProc("SetProcessDPIAware")
	procLoadCursorW                 = user32.NewProc("LoadCursorW")
	procGetWindowRect               = user32.NewProc("GetWindowRect")
	procSetLayeredWindowAttributes  = user32.NewProc("SetLayeredWindowAttributes")
	procTrackMouseEvent             = user32.NewProc("TrackMouseEvent")
	procCreateIconIndirect          = user32.NewProc("CreateIconIndirect")

	procShellNotifyIconW            = shell32.NewProc("Shell_NotifyIconW")

	procCreateCompatibleDC          = gdi32.NewProc("CreateCompatibleDC")
	procCreateCompatibleBitmap      = gdi32.NewProc("CreateCompatibleBitmap")
	procBitBlt                      = gdi32.NewProc("BitBlt")
	procDeleteDC                    = gdi32.NewProc("DeleteDC")
	procCreateRoundRectRgn          = gdi32.NewProc("CreateRoundRectRgn")
	procSetBkColor                  = gdi32.NewProc("SetBkColor")
	procGetStockObject              = gdi32.NewProc("GetStockObject")
	procCreateDIBSection            = gdi32.NewProc("CreateDIBSection")
	procCreateBitmap                = gdi32.NewProc("CreateBitmap")
	procCreateFontIndirectW         = gdi32.NewProc("CreateFontIndirectW")

	procDwmExtendFrameIntoClientArea = dwmapi.NewProc("DwmExtendFrameIntoClientArea")

	procGetModuleHandleW            = kernel32.NewProc("GetModuleHandleW")
	procGlobalAlloc                 = kernel32.NewProc("GlobalAlloc")
	procGlobalLock                  = kernel32.NewProc("GlobalLock")
	procGlobalUnlock                = kernel32.NewProc("GlobalUnlock")
	procGlobalFree                  = kernel32.NewProc("GlobalFree")

	procCreateStreamOnHGlobal       = ole32.NewProc("CreateStreamOnHGlobal")

	procGdiplusStartup              = gdiplus.NewProc("GdiplusStartup")
	procGdiplusShutdown             = gdiplus.NewProc("GdiplusShutdown")
	procGdipCreateBitmapFromStream  = gdiplus.NewProc("GdipCreateBitmapFromStream")
	procGdipDisposeImage            = gdiplus.NewProc("GdipDisposeImage")
	procGdipCreateHICONFromBitmap   = gdiplus.NewProc("GdipCreateHICONFromBitmap")
)

// ============================================================================
// Win32 constants
// ============================================================================

const (
	CS_VREDRAW = 0x0001
	CS_HREDRAW = 0x0002

	WS_OVERLAPPED   = 0x00000000
	WS_POPUP        = 0x80000000
	WS_CLIPCHILDREN = 0x02000000
	WS_CLIPSIBLINGS = 0x04000000

	WS_EX_LAYERED    = 0x00080000
	WS_EX_TOOLWINDOW = 0x00000080
	WS_EX_TOPMOST    = 0x00000008
	WS_EX_NOACTIVATE = 0x08000000

	WM_PAINT      = 0x000F
	WM_DESTROY    = 0x0002
	WM_MOUSEMOVE  = 0x0200
	WM_MOUSELEAVE = 0x02A3
	WM_LBUTTONUP  = 0x0202
	WM_RBUTTONUP  = 0x0205
	WM_KEYDOWN    = 0x0100
	WM_ACTIVATE   = 0x0006
	WM_KILLFOCUS  = 0x0008
	WM_NCCREATE   = 0x0081

	SW_SHOWNOACTIVATE = 4
	SW_SHOWNA         = 8

	HWND_TOPMOST   = ^uintptr(0)
	SWP_NOMOVE     = 0x0002
	SWP_NOSIZE     = 0x0001
	SWP_NOACTIVATE = 0x0010
	SWP_SHOWWINDOW = 0x0040
	SWP_NOZORDER   = 0x0004

	SM_CXSCREEN = 0
	SM_CYSCREEN = 1

	NIM_ADD    = 0x00000000
	NIM_DELETE = 0x00000002
	NIF_MESSAGE = 0x00000001
	NIF_ICON   = 0x00000002
	NIF_TIP    = 0x00000004

	SRCCOPY     = 0x00CC0020
	TRANSPARENT = 1
	PS_SOLID    = 0
	NULL_BRUSH  = 5
	NULL_PEN    = 8

	DT_LEFT       = 0x00000000
	DT_VCENTER    = 0x00000004
	DT_SINGLELINE = 0x00000020
	DT_NOPREFIX   = 0x00000800

	TME_LEAVE = 0x00000002

	GMEM_MOVEABLE = 2

	VK_ESCAPE = 0x1B
	IDC_ARROW = 32512

	// GWLP_USERDATA = -21
	GWLP_USERDATA = ^uintptr(20)
)

// ============================================================================
// Win32 structs
// ============================================================================

type WNDCLASSEXW struct {
	CbSize        uint32
	Style         uint32
	LpfnWndProc   uintptr
	CbClsExtra    int32
	CbWndExtra    int32
	HInstance     windows.Handle
	HIcon         windows.Handle
	HCursor       windows.Handle
	HbrBackground windows.Handle
	LpszMenuName  *uint16
	LpszClassName *uint16
	HIconSm       windows.Handle
}

type NOTIFYICONDATAW struct {
	CbSize           uint32
	HWnd             windows.Handle
	UID              uint32
	UFlags           uint32
	UCallbackMessage uint32
	HIcon            windows.Handle
	SzTip            [128]uint16
	DwState          uint32
	DwStateMask      uint32
	SzInfo           [256]uint16
	UVersion         uint32
	SzInfoTitle      [64]uint16
	DwInfoFlags      uint32
	GuidItem         windows.GUID
	HBalloonIcon     windows.Handle
}

type PAINTSTRUCT struct {
	Hdc         windows.Handle
	FErase      int32
	RcPaint     RECT
	FRestore    int32
	FIncUpdate  int32
	RgbReserved [32]byte
}

type RECT struct {
	Left   int32
	Top    int32
	Right  int32
	Bottom int32
}

type POINT struct {
	X int32
	Y int32
}

type MARGINS struct {
	CxLeftWidth    int32
	CxRightWidth   int32
	CyTopHeight    int32
	CyBottomHeight int32
}

type ICONINFO struct {
	FIcon    int32
	XHotspot uint32
	YHotspot uint32
	HbmMask  windows.Handle
	HbmColor windows.Handle
}

type BITMAPINFOHEADER struct {
	BiSize          uint32
	BiWidth         int32
	BiHeight        int32
	BiPlanes        uint16
	BiBitCount      uint16
	BiCompression   uint32
	BiSizeImage     uint32
	BiXPelsPerMeter int32
	BiYPelsPerMeter int32
	BiClrUsed       uint32
	BiClrImportant  uint32
}

type MSG struct {
	Hwnd    windows.Handle
	Message uint32
	WParam  uintptr
	LParam  uintptr
	Time    uint32
	Pt      POINT
}

type TRACKMOUSEEVENT struct {
	CbSize      uint32
	DwFlags     uint32
	HwndTrack   windows.Handle
	DwHoverTime uint32
}

type LOGFONTW struct {
	LfHeight         int32
	LfWidth          int32
	LfEscapement     int32
	LfOrientation    int32
	LfWeight         int32
	LfItalic         byte
	LfUnderline      byte
	LfStrikeOut      byte
	LfCharSet        byte
	LfOutPrecision   byte
	LfClipPrecision  byte
	LfQuality        byte
	LfPitchAndFamily byte
	LfFaceName       [32]uint16
}

// ============================================================================
// init: DPI awareness
// ============================================================================

func init() {
	procSetProcessDPIAware.Call()
}

// ============================================================================
// Tray icon management
// ============================================================================

func addTrayIcon(hwnd windows.Handle, iconData []byte) bool {
	hicon := createTrayIcon(iconData)

	var nid NOTIFYICONDATAW
	nid.CbSize = uint32(unsafe.Sizeof(nid))
	nid.HWnd = hwnd
	nid.UID = 1
	nid.UFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
	nid.UCallbackMessage = WM_TRAYICON
	nid.HIcon = hicon

	tip, _ := syscall.UTF16FromString("SDWAN Tray")
	copy(nid.SzTip[:], tip)

	ret, _, _ := procShellNotifyIconW.Call(NIM_ADD, uintptr(unsafe.Pointer(&nid)))
	return ret != 0
}

func deleteTrayIcon(hwnd windows.Handle) {
	var nid NOTIFYICONDATAW
	nid.CbSize = uint32(unsafe.Sizeof(nid))
	nid.HWnd = hwnd
	nid.UID = 1
	procShellNotifyIconW.Call(NIM_DELETE, uintptr(unsafe.Pointer(&nid)))
}

func createTrayIcon(iconData []byte) windows.Handle {
	if len(iconData) > 0 {
		if hicon := createIconFromPNG(iconData); hicon != 0 {
			return hicon
		}
	}
	return createFallbackIcon()
}

// createIconFromPNG loads a PNG icon from bytes using GDI+.
func createIconFromPNG(iconData []byte) windows.Handle {
	// Initialize GDI+
	var token uintptr
	input := struct {
		Version          uint32
		DebugCallback    uintptr
		SuppressBGThread int32
		SuppressExtCodecs int32
	}{Version: 1}

	ret, _, _ := procGdiplusStartup.Call(
		uintptr(unsafe.Pointer(&token)),
		uintptr(unsafe.Pointer(&input)),
		0,
	)
	if ret != 0 || token == 0 {
		return 0
	}
	defer procGdiplusShutdown.Call(token)

	// Allocate global memory and copy icon data
	hMem, _, _ := procGlobalAlloc.Call(GMEM_MOVEABLE, uintptr(len(iconData)))
	if hMem == 0 {
		return 0
	}
	defer procGlobalFree.Call(hMem)

	ptr, _, _ := procGlobalLock.Call(hMem)
	if ptr == 0 {
		return 0
	}
	defer procGlobalUnlock.Call(hMem)

	for i, b := range iconData {
		*(*byte)(unsafe.Add(unsafe.Pointer(ptr), i)) = b
	}
	procGlobalUnlock.Call(hMem)

	// Create stream from global memory
	var pStream uintptr
	ret, _, _ = procCreateStreamOnHGlobal.Call(hMem, 1, uintptr(unsafe.Pointer(&pStream))) // TRUE = auto-free
	if ret != 0 || pStream == 0 {
		return 0
	}
	defer callComRelease(pStream)

	// Load bitmap from stream
	var pBitmap uintptr
	ret, _, _ = procGdipCreateBitmapFromStream.Call(pStream, uintptr(unsafe.Pointer(&pBitmap)))
	if ret != 0 || pBitmap == 0 {
		return 0
	}
	defer procGdipDisposeImage.Call(pBitmap)

	// Create HICON from bitmap
	var hicon uintptr
	ret, _, _ = procGdipCreateHICONFromBitmap.Call(pBitmap, uintptr(unsafe.Pointer(&hicon)))
	if ret != 0 {
		return 0
	}
	return windows.Handle(hicon)
}

// callComRelease calls IUnknown::Release on a COM object.
func callComRelease(pUnknown uintptr) {
	if pUnknown == 0 {
		return
	}
	// Get vtable pointer (first field of the object)
	vtbl := *(*uintptr)(unsafe.Pointer(pUnknown))
	// Release is at vtable index 2 (0 = QueryInterface, 1 = AddRef, 2 = Release)
	offset := uintptr(2) * unsafe.Sizeof(uintptr(0))
	releaseFn := *(*uintptr)(unsafe.Pointer(vtbl + offset))
	syscall.Syscall(releaseFn, 1, pUnknown, 0, 0)
}

func getScreenDC() windows.Handle {
	dc, _, _ := procGetDC.Call(0)
	return windows.Handle(dc)
}

// createFallbackIcon creates a simple 32x32 blue circle icon programmatically.
func createFallbackIcon() windows.Handle {
	hdc := getScreenDC()
	if hdc == 0 {
		return 0
	}
	defer procReleaseDC.Call(0, uintptr(hdc))

	memDC, _, _ := procCreateCompatibleDC.Call(uintptr(hdc))
	if memDC == 0 {
		return 0
	}
	defer procDeleteDC.Call(memDC)

	var bmi BITMAPINFOHEADER
	bmi.BiSize = uint32(unsafe.Sizeof(bmi))
	bmi.BiWidth = 32
	bmi.BiHeight = 32
	bmi.BiPlanes = 1
	bmi.BiBitCount = 32

	var bits unsafe.Pointer
	hBmp, _, _ := procCreateDIBSection.Call(
		uintptr(hdc),
		uintptr(unsafe.Pointer(&bmi)),
		0,
		uintptr(unsafe.Pointer(&bits)),
		0, 0,
	)
	if hBmp == 0 || bits == nil {
		return 0
	}
	defer procDeleteObject.Call(hBmp)

	oldBmp, _, _ := procSelectObject.Call(memDC, hBmp)
	defer procSelectObject.Call(memDC, oldBmp)

	// Fill with transparent + blue circle (ARGB)
	pixels := (*[32 * 32]uint32)(bits)
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			dx := x - 16
			dy := y - 16
			dist := dx*dx + dy*dy
			if dist <= 12*12 {
				pixels[y*32+x] = 0xFF4285F4
			} else if dist <= 14*14 {
				alpha := uint32((14*14-dist)*255) / (14*14 - 12*12)
				if alpha > 255 {
					alpha = 255
				}
				pixels[y*32+x] = (alpha << 24) | 0x004285F4
			} else {
				pixels[y*32+x] = 0x00000000
			}
		}
	}

	// Create AND mask
	maskDC, _, _ := procCreateCompatibleDC.Call(uintptr(hdc))
	if maskDC == 0 {
		return 0
	}
	defer procDeleteDC.Call(maskDC)

	hMask, _, _ := procCreateBitmap.Call(32, 32, 1, 1, 0)
	if hMask == 0 {
		return 0
	}
	defer procDeleteObject.Call(hMask)

	oldMask, _, _ := procSelectObject.Call(maskDC, hMask)
	defer procSelectObject.Call(maskDC, oldMask)

	white, _, _ := procCreateSolidBrush.Call(0x00FFFFFF)
	r := RECT{0, 0, 32, 32}
	procFillRect.Call(maskDC, uintptr(unsafe.Pointer(&r)), white)
	procDeleteObject.Call(white)

	var ii ICONINFO
	ii.FIcon = 1
	ii.HbmMask = windows.Handle(hMask)
	ii.HbmColor = windows.Handle(hBmp)

	for attempt := 0; attempt < 2; attempt++ {
		ret, _, _ := procCreateIconIndirect.Call(uintptr(unsafe.Pointer(&ii)))
		if ret != 0 {
			return windows.Handle(ret)
		}
		ii.HbmColor = 0 // fallback: monochrome
	}
	return 0
}

// ============================================================================
// Popup window
// ============================================================================

type PopupWindow struct {
	hwnd     windows.Handle
	items    []MenuItem
	hovered  int
	expanded bool
}

// Popup dimensions (logical pixels, DPI-aware)
const (
	popupWidth       = 230
	itemHeight       = 38
	itemPaddingLeft  = 16
	itemPaddingRight = 16
	dividerHeight    = 17
	indentLeft       = 24
	topBottomPad     = 6
	hoverHInset      = 4
)

// COLORREF values (0x00BBGGRR format)
const (
	colorBackground = uint32(0x00FFFFFF) // #FFFFFF
	colorText       = uint32(0x001A1A1A) // #1A1A1A
	colorDisabled   = uint32(0x00999999) // #999999
	colorHoverBg    = uint32(0x00F2F2F2) // #F2F2F2
	colorHoverBar   = uint32(0x00FF7A00) // #007AFF
	colorDivider    = uint32(0x00E8E8E8) // #E8E8E8
	colorGreen      = uint32(0x0059C734) // #34C759
	colorGray       = uint32(0x00CCCCCC) // #CCC
)

const (
	trayClassName   = "SDWANTrayClass"
	popupClassName  = "SDWANPopupClass"
	WM_TRAYICON     = uint32(0x0400 + 1)
)

var appHwnd windows.Handle
var globalPopup *PopupWindow

func PostQuitMessage() {
	procPostQuitMessage.Call(0)
}

// calcPopupHeight computes total popup window height.
func (pw *PopupWindow) calcPopupHeight() int32 {
	h := int32(topBottomPad * 2)
	for _, item := range pw.items {
		if item.Action == ActionSelectServer && !pw.expanded {
			continue
		}
		if item.Action == ActionDivider {
			h += int32(dividerHeight)
		} else {
			h += int32(itemHeight)
		}
	}
	return h
}

// visibleItemAt returns the visible MenuItem at pixel Y and its visual index.
func (pw *PopupWindow) visibleItemAt(py int32) (*MenuItem, int) {
	y := int32(topBottomPad)
	vi := 0
	for i := range pw.items {
		item := pw.items[i]
		if item.Action == ActionSelectServer && !pw.expanded {
			continue
		}
		var h int32
		if item.Action == ActionDivider {
			h = int32(dividerHeight)
		} else {
			h = int32(itemHeight)
		}
		if py >= y && py < y+h {
			return &pw.items[i], vi
		}
		y += h
		vi++
	}
	return nil, -1
}

// CreatePopup creates and shows the popup window near the cursor.
func CreatePopup(state *MenuState) *PopupWindow {
	pw := &PopupWindow{
		items:    BuildMenuItems(state),
		expanded: false,
		hovered:  -1,
	}

	var pt POINT
	procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))

	hInstance, _, _ := procGetModuleHandleW.Call(0)

	popupClassPtr, _ := windows.UTF16PtrFromString(popupClassName)

	popupH := pw.calcPopupHeight()

	exStyle := uint32(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE)
	windowStyle := uint32(WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS)

	// Position near cursor
	x := pt.X - popupWidth/2
	y := pt.Y + 8

	screenW, _, _ := procGetSystemMetrics.Call(SM_CXSCREEN, 0, 0)
	screenH, _, _ := procGetSystemMetrics.Call(SM_CYSCREEN, 0, 0)
	sw := int32(screenW)
	sh := int32(screenH)
	if x < 0 {
		x = 0
	}
	if x+popupWidth > sw {
		x = sw - popupWidth
	}
	if y+popupH > sh {
		y = pt.Y - popupH - 8
	}

	title, _ := windows.UTF16PtrFromString("SDWAN Popup")

	hwnd, _, _ := procCreateWindowExW.Call(
		uintptr(exStyle),
		uintptr(unsafe.Pointer(popupClassPtr)),
		uintptr(unsafe.Pointer(title)),
		uintptr(windowStyle),
		uintptr(x), uintptr(y),
		uintptr(popupWidth), uintptr(popupH),
		0, 0,
		hInstance,
		uintptr(unsafe.Pointer(pw)),
	)
	pw.hwnd = windows.Handle(hwnd)

	// Round corners (10px radius)
	rgn, _, _ := procCreateRoundRectRgn.Call(0, 0, uintptr(popupWidth+1), uintptr(popupH+1), 10, 10)
	if rgn != 0 {
		procSetWindowRgn.Call(hwnd, rgn, 1)
	}

	// DWM shadow (works on Windows 10+, silently fails on older)
	margins := MARGINS{CxLeftWidth: 0, CxRightWidth: 0, CyTopHeight: 0, CyBottomHeight: 1}
	procDwmExtendFrameIntoClientArea.Call(hwnd, uintptr(unsafe.Pointer(&margins)))

	// Show window
	procSetLayeredWindowAttributes.Call(hwnd, 0x00FFFFFF, 255, 2) // LWA_ALPHA
	procShowWindow.Call(hwnd, uintptr(SW_SHOWNOACTIVATE))
	procUpdateWindow.Call(hwnd)
	procSetWindowPos.Call(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW)

	globalPopup = pw
	return pw
}

// Hide destroys the popup window.
func (pw *PopupWindow) Hide() {
	if pw.hwnd != 0 {
		procDestroyWindow.Call(uintptr(pw.hwnd))
		pw.hwnd = 0
	}
	if globalPopup == pw {
		globalPopup = nil
	}
}

// Refresh rebuilds items and repaints.
func (pw *PopupWindow) Refresh(state *MenuState) {
	pw.items = BuildMenuItems(state)
	procInvalidateRect.Call(uintptr(pw.hwnd), 0, 1)
}

// ============================================================================
// Popup Window Procedure
// ============================================================================

func popupWndProc(hwndU windows.Handle, msg uint32, wParam, lParam uintptr) uintptr {
	hwnd := uintptr(hwndU)

	ptr, _, _ := procGetWindowLongPtrW.Call(hwnd, uintptr(GWLP_USERDATA))
	pw := (*PopupWindow)(unsafe.Pointer(ptr))

	switch msg {
	case WM_NCCREATE:
		cs := (*struct {
			LpCreateParams uintptr
			HInstance      uintptr
			HMenu          uintptr
			HwndParent     uintptr
			Cy             int32
			Cx             int32
			Y              int32
			X              int32
			Style          int32
			LpszName       *uint16
			LpszClass      *uint16
			DwExStyle      uint32
		})(unsafe.Pointer(lParam))
		procSetWindowLongPtrW.Call(hwnd, uintptr(GWLP_USERDATA), cs.LpCreateParams)
		return 1

	case WM_PAINT:
		if pw != nil {
			pw.handlePaint(hwndU)
		}
		return 0

	case WM_MOUSEMOVE:
		if pw != nil {
			// Track mouse leave
			var tme TRACKMOUSEEVENT
			tme.CbSize = uint32(unsafe.Sizeof(tme))
			tme.DwFlags = TME_LEAVE
			tme.HwndTrack = hwndU
			procTrackMouseEvent.Call(uintptr(unsafe.Pointer(&tme)))

			py := int32(int16(lParam & 0xFFFF))
			_, vi := pw.visibleItemAt(py)
			if pw.hovered != vi {
				pw.hovered = vi
				procInvalidateRect.Call(hwnd, 0, 0)
			}
		}
		return 0

	case WM_MOUSELEAVE:
		if pw != nil {
			pw.hovered = -1
			procInvalidateRect.Call(hwnd, 0, 0)
		}
		return 0

	case WM_LBUTTONUP:
		if pw == nil {
			return 0
		}
		py := int32(int16(lParam & 0xFFFF))
		item, _ := pw.visibleItemAt(py)
		if item != nil {
			switch item.Action {
			case ActionServerGroup:
				pw.expanded = !pw.expanded
				pw.hovered = -1
				pw.resizeWindow()
			case ActionStatus, ActionDivider:
				// no-op
			default:
				if !item.Disabled {
					pw.Hide()
					HandlePopupClick(*item)
				}
			}
		}
		return 0

	case WM_KEYDOWN:
		if wParam == uintptr(VK_ESCAPE) && pw != nil {
			pw.Hide()
		}
		return 0

	case WM_ACTIVATE:
		if uint16(wParam&0xFFFF) == 0 && pw != nil { // WA_INACTIVE
			pw.Hide()
		}
		return 0

	case WM_KILLFOCUS:
		if pw != nil {
			pw.Hide()
		}
		return 0
	}

	ret, _, _ := procDefWindowProcW.Call(hwnd, uintptr(msg), wParam, lParam)
	return ret
}

// resizeWindow adjusts the popup height after expand/collapse.
func (pw *PopupWindow) resizeWindow() {
	newH := int32(pw.calcPopupHeight())
	var rect RECT
	procGetWindowRect.Call(uintptr(pw.hwnd), uintptr(unsafe.Pointer(&rect)))
	width := rect.Right - rect.Left

	rgn, _, _ := procCreateRoundRectRgn.Call(0, 0, uintptr(width+1), uintptr(newH+1), 10, 10)
	if rgn != 0 {
		procSetWindowRgn.Call(uintptr(pw.hwnd), rgn, 1)
	}

	procSetWindowPos.Call(
		uintptr(pw.hwnd), 0,
		uintptr(rect.Left), uintptr(rect.Top),
		uintptr(width), uintptr(newH),
		SWP_NOACTIVATE|SWP_NOZORDER,
	)
	procInvalidateRect.Call(uintptr(pw.hwnd), 0, 1)
}

// ============================================================================
// Custom Drawing (WM_PAINT handler for popup)
// ============================================================================

func (pw *PopupWindow) handlePaint(hwndU windows.Handle) {
	hwnd := uintptr(hwndU)
	var ps PAINTSTRUCT
	hdc, _, _ := procBeginPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))
	if hdc == 0 {
		return
	}
	defer procEndPaint.Call(hwnd, uintptr(unsafe.Pointer(&ps)))

	var rect RECT
	procGetClientRect.Call(hwnd, uintptr(unsafe.Pointer(&rect)))
	w32 := int32(rect.Right - rect.Left)
	h32 := int32(rect.Bottom - rect.Top)

	// Double-buffering
	memDC, _, _ := procCreateCompatibleDC.Call(hdc)
	if memDC == 0 {
		return
	}
	defer procDeleteDC.Call(memDC)

	bmp, _, _ := procCreateCompatibleBitmap.Call(hdc, uintptr(w32), uintptr(h32))
	if bmp == 0 {
		return
	}
	defer procDeleteObject.Call(bmp)

	oldBmp, _, _ := procSelectObject.Call(memDC, bmp)
	defer procSelectObject.Call(memDC, oldBmp)

	// White background
	bgBrush, _, _ := procCreateSolidBrush.Call(uintptr(colorBackground))
	procFillRect.Call(memDC, uintptr(unsafe.Pointer(&rect)), bgBrush)
	procDeleteObject.Call(bgBrush)

	// Select font
	font := getPopupFont()
	if font != 0 {
		procSelectObject.Call(memDC, uintptr(font))
		defer procDeleteObject.Call(uintptr(font))
	}
	procSetBkMode.Call(memDC, TRANSPARENT)

	y := int32(topBottomPad)
	vi := 0
	for i := range pw.items {
		item := &pw.items[i]

		if item.Action == ActionSelectServer && !pw.expanded {
			continue
		}

		if item.Action == ActionDivider {
			divPen, _, _ := procCreatePen.Call(PS_SOLID, 1, uintptr(colorDivider))
			oldPen, _, _ := procSelectObject.Call(memDC, divPen)
			divY := y + 8
			procMoveToEx.Call(memDC, uintptr(itemPaddingLeft), uintptr(divY), 0)
			procLineTo.Call(memDC, uintptr(w32-itemPaddingRight), uintptr(divY))
			procSelectObject.Call(memDC, oldPen)
			procDeleteObject.Call(divPen)
			y += int32(dividerHeight)
			vi++
			continue
		}

		itemH := int32(itemHeight)

		// Hover highlight
		if vi == pw.hovered && !item.Disabled && item.Action != ActionStatus {
			hoverBrush, _, _ := procCreateSolidBrush.Call(uintptr(colorHoverBg))
			nullPen, _, _ := procGetStockObject.Call(NULL_PEN)
			oldBrush, _, _ := procSelectObject.Call(memDC, hoverBrush)
			oldNullPen, _, _ := procSelectObject.Call(memDC, nullPen)

			hLeft := int32(itemPaddingLeft) - int32(hoverHInset)
			hRight := w32 - int32(itemPaddingRight) + int32(hoverHInset)
			procRoundRect.Call(memDC,
				uintptr(hLeft), uintptr(y+2),
				uintptr(hRight), uintptr(y+itemH-2),
				6, 6,
			)

			procSelectObject.Call(memDC, oldBrush)
			procSelectObject.Call(memDC, oldNullPen)
			procDeleteObject.Call(hoverBrush)

			// Left color bar (3px)
			if item.Action != ActionServerGroup {
				barBrush, _, _ := procCreateSolidBrush.Call(uintptr(colorHoverBar))
				barRect := RECT{hLeft, y + 6, hLeft + 3, y + itemH - 6}
				procFillRect.Call(memDC, uintptr(unsafe.Pointer(&barRect)), barBrush)
				procDeleteObject.Call(barBrush)
			}
		}

		// Text position
		textLeft := int32(itemPaddingLeft)
		if item.Indented {
			textLeft = int32(indentLeft)
		}

		// Text color
		if item.Disabled {
			procSetTextColor.Call(memDC, uintptr(colorDisabled))
		} else {
			procSetTextColor.Call(memDC, uintptr(colorText))
		}

		dotRadius := int32(4)

		// Selected server: blue dot
		if item.Action == ActionSelectServer && item.Selected {
			dotBrush, _, _ := procCreateSolidBrush.Call(uintptr(colorHoverBar))
			dotPen, _, _ := procCreatePen.Call(PS_SOLID, 1, uintptr(colorHoverBar))
			oldBrush2, _, _ := procSelectObject.Call(memDC, dotBrush)
			oldPen2, _, _ := procSelectObject.Call(memDC, dotPen)
			cx := textLeft + 5
			cy := y + itemH/2
			procEllipse.Call(memDC,
				uintptr(cx-dotRadius), uintptr(cy-dotRadius),
				uintptr(cx+dotRadius), uintptr(cy+dotRadius),
			)
			procSelectObject.Call(memDC, oldBrush2)
			procSelectObject.Call(memDC, oldPen2)
			procDeleteObject.Call(dotBrush)
			procDeleteObject.Call(dotPen)
		}

		// Status dot (green/gray)
		if item.Action == ActionStatus {
			dotColor := colorGray
			if item.Selected {
				dotColor = colorGreen
			}
			dotBrush, _, _ := procCreateSolidBrush.Call(uintptr(dotColor))
			dotPen, _, _ := procCreatePen.Call(PS_SOLID, 1, uintptr(dotColor))
			oldBrush2, _, _ := procSelectObject.Call(memDC, dotBrush)
			oldPen2, _, _ := procSelectObject.Call(memDC, dotPen)
			cx := textLeft + 5
			cy := y + itemH/2
			procEllipse.Call(memDC,
				uintptr(cx-dotRadius), uintptr(cy-dotRadius),
				uintptr(cx+dotRadius), uintptr(cy+dotRadius),
			)
			procSelectObject.Call(memDC, oldBrush2)
			procSelectObject.Call(memDC, oldPen2)
			procDeleteObject.Call(dotBrush)
			procDeleteObject.Call(dotPen)
			textLeft += 12
		}

		// Draw label text
		labelPtr, _ := windows.UTF16PtrFromString(item.Label)
		textRect := RECT{textLeft, y, w32 - int32(itemPaddingRight), y + itemH}
		dtFlags := uintptr(DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX)
		procDrawTextW.Call(memDC, uintptr(unsafe.Pointer(labelPtr)), ^uintptr(0), uintptr(unsafe.Pointer(&textRect)), dtFlags)

		y += itemH
		vi++
	}

	// Blit to screen
	procBitBlt.Call(hdc, 0, 0, uintptr(w32), uintptr(h32), memDC, 0, 0, SRCCOPY)
}

// getPopupFont creates the "Segoe UI" 13pt font handle.
func getPopupFont() windows.Handle {
	var lf LOGFONTW
	lf.LfHeight = -17 // 13pt at 96 DPI
	lf.LfWeight = 400  // FW_NORMAL
	lf.LfCharSet = 1    // DEFAULT_CHARSET
	lf.LfQuality = 4    // CLEARTYPE_QUALITY

	name, _ := syscall.UTF16FromString("Segoe UI")
	copy(lf.LfFaceName[:], name)

	font, _, _ := procCreateFontIndirectW.Call(uintptr(unsafe.Pointer(&lf)))
	return windows.Handle(font)
}

// ============================================================================
// Tray message window
// ============================================================================

// Window procedure callbacks — created once at startup.
var (
	popupWndProcCB = syscall.NewCallback(popupWndProc)
	trayWndProcCB  = syscall.NewCallback(trayWndProc)
)

// registerClasses registers the popup and tray window classes with Win32.
// Must be called once before any window creation.
func registerClasses() {
	hInstance, _, _ := procGetModuleHandleW.Call(0)
	cursor, _, _ := procLoadCursorW.Call(0, uintptr(IDC_ARROW))
	hCur := windows.Handle(cursor)

	// Popup window class
	popupClassPtr, _ := windows.UTF16PtrFromString(popupClassName)
	var wc WNDCLASSEXW
	wc.CbSize = uint32(unsafe.Sizeof(wc))
	wc.LpfnWndProc = popupWndProcCB
	wc.HInstance = windows.Handle(hInstance)
	wc.HCursor = hCur
	wc.LpszClassName = popupClassPtr
	wc.Style = CS_HREDRAW | CS_VREDRAW
	procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))

	// Tray window class
	trayClassPtr, _ := windows.UTF16PtrFromString(trayClassName)
	wc.LpszClassName = trayClassPtr
	wc.LpfnWndProc = trayWndProcCB
	procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
}

func trayWndProc(hwndU windows.Handle, msg uint32, wParam, lParam uintptr) uintptr {
	switch msg {
	case WM_TRAYICON:
		switch uint32(lParam) {
		case WM_RBUTTONUP, WM_LBUTTONUP:
			if globalPopup != nil {
				globalPopup.Hide()
			}
			procSetForegroundWindow.Call(uintptr(hwndU))
			CreatePopup(menuState)
		}
		return 0

	case WM_DESTROY:
		deleteTrayIcon(hwndU)
		procPostQuitMessage.Call(0)
		return 0
	}

	ret, _, _ := procDefWindowProcW.Call(uintptr(hwndU), uintptr(msg), wParam, lParam)
	return ret
}

// RunMessageLoop creates the tray window and enters the Windows message pump.
// Returns the exit code.
func RunMessageLoop(iconData []byte) int {
	registerClasses()

	hInstance, _, _ := procGetModuleHandleW.Call(0)

	appClassPtr, _ := windows.UTF16PtrFromString(trayClassName)
	titlePtr, _ := windows.UTF16PtrFromString("SDWAN Tray")

	hwnd, _, _ := procCreateWindowExW.Call(
		0,
		uintptr(unsafe.Pointer(appClassPtr)),
		uintptr(unsafe.Pointer(titlePtr)),
		uintptr(WS_OVERLAPPED),
		0, 0, 0, 0,
		0, 0,
		hInstance,
		0,
	)

	hw := windows.Handle(hwnd)
	if hw == 0 {
		return 1
	}
	appHwnd = hw

	if !addTrayIcon(hw, iconData) {
		procDestroyWindow.Call(hwnd)
		return 1
	}

	var msg MSG
	for {
		ret, _, _ := procGetMessageW.Call(
			uintptr(unsafe.Pointer(&msg)),
			0, 0, 0,
		)
		if ret == 0 || int32(ret) == -1 {
			break
		}
		procTranslateMessage.Call(uintptr(unsafe.Pointer(&msg)))
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&msg)))
	}

	deleteTrayIcon(hw)
	return int(msg.WParam)
}
