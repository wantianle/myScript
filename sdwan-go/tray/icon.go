package main

import (
	"bytes"
	_ "embed"
	"image"
	"image/color"
	"image/png"
)

//go:embed icon.png
var embeddedIcon []byte

// generateIcon returns the embedded icon.png, or falls back to a simple
// placeholder circle if no icon.png is found.
// To use a custom icon: just drop your 32x32 PNG file as tray/icon.png.
func generateIcon() []byte {
	if len(embeddedIcon) > 0 {
		return embeddedIcon
	}

	// Fallback: simple blue circle (32x32)
	img := image.NewRGBA(image.Rect(0, 0, 32, 32))
	blue := color.RGBA{R: 66, G: 133, B: 244, A: 255}
	for y := 0; y < 32; y++ {
		for x := 0; x < 32; x++ {
			dx := x - 16
			dy := y - 16
			if dx*dx+dy*dy <= 14*14 {
				img.Set(x, y, blue)
			}
		}
	}
	var buf bytes.Buffer
	png.Encode(&buf, img)
	return buf.Bytes()
}
