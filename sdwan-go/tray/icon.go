package main

import (
	"bytes"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"log"
)

// generateIcon creates a 32x32 PNG icon representing a VPN/tunnel connection.
// Blue circle with a white border and a simple "V" shape in white.
func generateIcon() []byte {
	const size = 32
	img := image.NewRGBA(image.Rect(0, 0, size, size))

	center := size / 2
	radius := size/2 - 1

	blue := color.RGBA{R: 0, G: 100, B: 200, A: 255}
	darkBlue := color.RGBA{R: 0, G: 60, B: 140, A: 255}
	white := color.RGBA{R: 255, G: 255, B: 255, A: 255}

	// Fill with transparent background
	draw.Draw(img, img.Bounds(), &image.Uniform{color.Transparent}, image.Point{}, draw.Src)

	// Draw filled blue circle
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			dx := x - center
			dy := y - center
			dist := dx*dx + dy*dy

			// Outer border (white ring)
			if dist <= radius*radius && dist >= (radius-3)*(radius-3) {
				img.Set(x, y, white)
			}
			// Inner fill (blue gradient)
			if dist <= (radius-3)*(radius-3) {
				if dist > (radius-6)*(radius-6) {
					img.Set(x, y, darkBlue)
				} else {
					img.Set(x, y, blue)
				}
			}
		}
	}

	// Draw a simple "key/tunnel" icon in the center: two connected horizontal lines
	// Top bar of the keyhole shape
	barTop := center - 6
	barBottom := center + 2
	barLeft := center - 6
	barRight := center + 6

	for y := barTop; y <= barBottom; y++ {
		for x := barLeft; x <= barRight; x++ {
			if x >= 0 && x < size && y >= 0 && y < size {
				if y == barTop || y == barBottom || y == center-1 {
					img.Set(x, y, white)
				} else if x == barLeft || x == barRight {
					img.Set(x, y, white)
				}
			}
		}
	}

	// Bottom stem of the keyhole
	stemTop := center + 3
	stemBottom := center + 7
	stemLeft := center - 2
	stemRight := center + 2

	for y := stemTop; y <= stemBottom; y++ {
		for x := stemLeft; x <= stemRight; x++ {
			if x >= 0 && x < size && y >= 0 && y < size {
				if x == stemLeft || x == stemRight || y == stemBottom {
					img.Set(x, y, white)
				}
			}
		}
	}

	var buf bytes.Buffer
	if err := png.Encode(&buf, img); err != nil {
		log.Printf("Error generating icon: %v", err)
		// Return a minimal 1x1 PNG as fallback
		fallback := image.NewRGBA(image.Rect(0, 0, 1, 1))
		fallback.Set(0, 0, blue)
		var fb bytes.Buffer
		png.Encode(&fb, fallback)
		return fb.Bytes()
	}
	return buf.Bytes()
}
