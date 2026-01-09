import os
import torch
import comfy
from PIL import Image,ImageOps
import numpy as np


class Maoyu_LoadImgBatch:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
            },
            "optional": {
                "image_load_cap": ("INT", {"default": 0, "min": 0, "step": 1}),
                "start_index": ("INT", {"default": 0, "min": 0, "step": 1}),
                "load_always": ("BOOLEAN", {"default": False, "label_on": "enabled", "label_off": "disabled"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "LIST",)
    FUNCTION = "load_images"

    CATEGORY = "maoyu/dir"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if 'load_always' in kwargs and kwargs['load_always']:
            return float("NaN")
        else:
            return hash(frozenset(kwargs))

    def load_images(self, directory: str, image_load_cap: int = 0, start_index: int = 0, load_always=False):
        if not os.path.isdir(directory):
            raise FileNotFoundError(f"Directory '{directory} cannot be found.'")
        dir_files = os.listdir(directory)
        if len(dir_files) == 0:
            raise FileNotFoundError(f"No files in directory '{directory}'.")

        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        dir_files = [f for f in dir_files if any(f.lower().endswith(ext) for ext in valid_extensions)]

        dir_files = sorted(dir_files)
        dir_files = [os.path.join(directory, x) for x in dir_files]

        dir_files = dir_files[start_index:]

        images = []
        masks = []

        limit_images = False
        if image_load_cap > 0:
            limit_images = True
        image_count = 0

        has_non_empty_mask = False
        path_list = []
        for image_path in dir_files:
            if os.path.isdir(image_path) and os.path.exists(image_path):
                continue
            if limit_images and image_count >= image_load_cap:
                break
            i = Image.open(image_path)
            i = ImageOps.exif_transpose(i)
            image = i.convert("RGB")
            image = np.array(image).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]
            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
                has_non_empty_mask = True
            else:
                mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
            images.append(image)
            masks.append(mask)
            image_path = os.path.basename(image_path)
            image_path_list = image_path.split(".")
            path_list.append(image_path_list[0])
            image_count += 1

        if len(images) == 1:
            return (images[0], masks[0], 1, path_list)

        elif len(images) > 1:
            image1 = images[0]
            mask1 = None

            for image2 in images[1:]:
                if image1.shape[1:] != image2.shape[1:]:
                    image2 = comfy.utils.common_upscale(image2.movedim(-1, 1), image1.shape[2], image1.shape[1], "bilinear", "center").movedim(1, -1)
                image1 = torch.cat((image1, image2), dim=0)

            for mask2 in masks[1:]:
                if has_non_empty_mask:
                    if image1.shape[1:3] != mask2.shape:
                        mask2 = torch.nn.functional.interpolate(mask2.unsqueeze(0).unsqueeze(0), size=(image1.shape[2], image1.shape[1]), mode='bilinear', align_corners=False)
                        mask2 = mask2.squeeze(0)
                    else:
                        mask2 = mask2.unsqueeze(0)
                else:
                    mask2 = mask2.unsqueeze(0)

                if mask1 is None:
                    mask1 = mask2
                else:
                    mask1 = torch.cat((mask1, mask2), dim=0)

            return (image1, mask1, len(images), path_list)

class Maoyu_PathFromBatch:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"path_list": ("LIST", ),
                              "batch_index": ("INT", {"default": 0, "min": 0, "max": 4095}),
                              "length": ("INT", {"default": 1, "min": 1, "max": 4096}),
                              }}
    RETURN_TYPES = ("STRING", "LIST")
    RETURN_NAMES = ("text", 'list')
    FUNCTION = "filepath"

    CATEGORY = "maoyu/dir"

    def filepath(self, path_list, batch_index, length):
        s_in = path_list
        batch_index = min(len(s_in) - 1, batch_index)
        length = min(len(s_in) - batch_index, length)
        s = s_in[batch_index:batch_index + length]
        return (','.join(s), s)

class Maoyu_ListToString:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"string_list": ("LIST",)}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "list_to_strings"
    
    CATEGORY = "maoyu/dir"
    
    def list_to_strings(self, string_list):
        return (','.join(string_list),)


NODE_CLASS_MAPPINGS = {
    "Maoyu_LoadImgBatch": Maoyu_LoadImgBatch,
    "Maoyu_PathFromBatch": Maoyu_PathFromBatch,
    "Maoyu_ListToString": Maoyu_ListToString,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Maoyu_LoadImgBatch": "批量加载图片 (Load Img Batch)",
    "Maoyu_PathFromBatch": "批量路径提取 (Path From Batch)",
    "Maoyu_ListToString": "列表转字符串 (List To String)",
}
