"""Small manifest thumbnails using Tk or Windows' built-in GDI+ image codecs."""
import ctypes
import os
import tkinter as tk


def fit_size(width,height,box=24):
    if width<=0 or height<=0 or width*height>32_000_000:raise ValueError('Image dimensions exceed preview limit')
    scale=min(box/width,box/height,1)
    return max(1,round(width*scale)),max(1,round(height*scale))


def rgb_pixel(argb,background=(24,53,66)):
    alpha=(argb>>24)&255
    color=((argb>>16)&255,(argb>>8)&255,argb&255)
    return bytes((v*alpha+b*(255-alpha)+127)//255 for v,b in zip(color,background))


def windows_ppm(path,box=24):
    lib=ctypes.WinDLL('gdiplus',use_last_error=True)
    pointer=ctypes.c_void_p;uint=ctypes.c_uint32
    class Startup(ctypes.Structure):
        _fields_=[('version',uint),('callback',pointer),('background',ctypes.c_int32),('external',ctypes.c_int32)]
    lib.GdiplusStartup.argtypes=[ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(Startup),pointer]
    lib.GdiplusShutdown.argtypes=[ctypes.c_size_t];lib.GdiplusShutdown.restype=None
    lib.GdipLoadImageFromFile.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(pointer)]
    lib.GdipGetImageWidth.argtypes=[pointer,ctypes.POINTER(uint)]
    lib.GdipGetImageHeight.argtypes=[pointer,ctypes.POINTER(uint)]
    lib.GdipGetImageThumbnail.argtypes=[pointer,uint,uint,ctypes.POINTER(pointer),pointer,pointer]
    lib.GdipBitmapGetPixel.argtypes=[pointer,ctypes.c_int32,ctypes.c_int32,ctypes.POINTER(uint)]
    lib.GdipDisposeImage.argtypes=[pointer]
    token=ctypes.c_size_t();image=pointer();thumb=pointer()
    def check(code):
        if code:raise ValueError('Windows could not decode this mod image')
    check(lib.GdiplusStartup(ctypes.byref(token),ctypes.byref(Startup(1,None,0,1)),None))
    try:
        check(lib.GdipLoadImageFromFile(str(path),ctypes.byref(image)))
        w,h=uint(),uint();check(lib.GdipGetImageWidth(image,ctypes.byref(w)));check(lib.GdipGetImageHeight(image,ctypes.byref(h)))
        width,height=fit_size(w.value,h.value,box)
        check(lib.GdipGetImageThumbnail(image,width,height,ctypes.byref(thumb),None,None))
        pixels=bytearray();argb=uint()
        for y in range(height):
            for x in range(width):
                check(lib.GdipBitmapGetPixel(thumb,x,y,ctypes.byref(argb)))
                pixels.extend(rgb_pixel(argb.value))
        return f'P6\n{width} {height}\n255\n'.encode()+pixels
    finally:
        if thumb.value:lib.GdipDisposeImage(thumb)
        if image.value:lib.GdipDisposeImage(image)
        lib.GdiplusShutdown(token)


def thumbnail(master,path,box=24):
    if os.name=='nt':
        try:return tk.PhotoImage(master=master,data=windows_ppm(path,box),format='PPM')
        except (ValueError,OSError):pass
    # Tk supplies native PNG/GIF/PPM support if a Windows codec is unavailable.
    image=tk.PhotoImage(master=master,file=str(path))
    fit_size(image.width(),image.height(),box)
    scale=max(1,(max(image.width(),image.height())+box-1)//box)
    return image.subsample(scale,scale)
