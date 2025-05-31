import json
from datetime import datetime
from PIL import Image, ImageDraw, ImageOps, ExifTags
import logging
from pathlib import Path
import piexif
import os
import time
import shutil
from iptcinfo3 import IPTCInfo

# ANSI escape codes for text styling
STYLING = {
    "GREEN": "\033[92m",
    "RED": "\033[91m",
    "BLUE": "\033[94m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m",
}

#Setup log styling
class ColorFormatter(logging.Formatter):
    def format(self, record):
        message = super().format(record)
        if record.levelno == logging.INFO and "Finished processing" not in record.msg and "Re-saved" not in record.msg:
            message = STYLING["GREEN"] + message + STYLING["RESET"]
        elif record.levelno == logging.ERROR:
            message = STYLING["RED"] + message + STYLING["RESET"]
        elif "Finished processing" in record.msg or "Re-saved" in record.msg:  # Identify the summary message
            message = STYLING["BLUE"] + STYLING["BOLD"] + message + STYLING["RESET"]
        return message

# Setup basic logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Setup logging with styling
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()
handler = logger.handlers[0]  # Get the default handler installed by basicConfig
handler.setFormatter(ColorFormatter('%(asctime)s - %(levelname)s - %(message)s'))

# Initialize counters
processed_files_count = 0
converted_files_count = 0
combined_files_count = 0
skipped_files_count = 0

# Static IPTC tags
source_app = "BeReal app"
processing_tool = "github/bereal-gdpr-photo-toolkit"
#keywords = ["BeReal"]

# Define lists to hold the paths of images to be combined
primary_images = []
secondary_images = []

# Define paths using pathlib
photo_folder = Path('Photos/post/')
bereal_folder = Path('Photos/bereal')
output_folder = Path('Photos/post/__processed')
output_folder_combined = Path('Photos/post/__combined')
output_folder.mkdir(parents=True, exist_ok=True)  # Create the output folder if it doesn't exist

# Print the paths
print(STYLING["BOLD"] + "\nThe following paths are set for the input and output files:" + STYLING["RESET"])
print(f"Photo folder: {photo_folder}")
if os.path.exists(bereal_folder):
    print(f"Older photo folder: {bereal_folder}")
print(f"Output folder for singular images: {output_folder}")
print(f"Output folder for combined images: {output_folder_combined}")
#print("\nDeduplication is active. No files will be overwritten or deleted.")
print("")

# Function to count number of input files
def count_files_in_folder(folder_path):
    folder = Path(folder_path)
    file_count = len(list(folder.glob('*.webp')))
    return file_count

number_of_files = count_files_in_folder(photo_folder)
print(f"Number of WebP-files in {photo_folder}: {number_of_files}")

if os.path.exists(bereal_folder):
    number_of_files_bereal = count_files_in_folder(bereal_folder) # Use a different variable name
    print(f"Number of (older) WebP-files in {bereal_folder}: {number_of_files_bereal}")

# Settings
## Initial choice for accessing advanced settings
print(STYLING["BOLD"] + "\nDo you want to access advanced settings or run with default settings?" + STYLING["RESET"])
print("Default settings are:\n"
"1. Copied images are converted from WebP to JPEG\n"
"2. Converted images' filenames do not contain the original filename\n"
"3. Combined images are created on top of converted, singular images")
advanced_settings = input("\nEnter " + STYLING["BOLD"] + "'yes'" + STYLING["RESET"] + "for advanced settings or press any key to continue with default settings: ").strip().lower()

if advanced_settings != 'yes':
    print("Continuing with default settings.\n")

## Default responses
convert_to_jpeg = 'yes'
keep_original_filename = 'no'
create_combined_images = 'yes'

## Proceed with advanced settings if chosen
if advanced_settings == 'yes':
    # User choice for converting to JPEG
    convert_to_jpeg = None
    while convert_to_jpeg not in ['yes', 'no']:
        convert_to_jpeg = input(STYLING["BOLD"] + "\n1. Do you want to convert images from WebP to JPEG? (yes/no): " + STYLING["RESET"]).strip().lower()
        if convert_to_jpeg == 'no':
            print("Your images will not be converted. No additional metadata will be added.")
        if convert_to_jpeg not in ['yes', 'no']:
            logging.error("Invalid input. Please enter 'yes' or 'no'.")

    # User choice for keeping original filename
    print(STYLING["BOLD"] + "\n2. There are two options for how output files can be named" + STYLING["RESET"] + "\n"
    "Option 1: YYYY-MM-DDTHH-MM-SS_primary/secondary_original-filename.jpeg\n"
    "Option 2: YYYY-MM-DDTHH-MM-SS_primary/secondary.jpeg\n"
    "This will only influence the naming scheme of singular images.")
    keep_original_filename = None
    while keep_original_filename not in ['yes', 'no']:
        keep_original_filename = input(STYLING["BOLD"] + "Do you want to keep the original filename in the renamed file? (yes/no): " + STYLING["RESET"]).strip().lower()
        if keep_original_filename not in ['yes', 'no']:
            logging.error("Invalid input. Please enter 'yes' or 'no'.")

    # User choice for creating combined images
    create_combined_images = None
    while create_combined_images not in ['yes', 'no']:
        create_combined_images = input(STYLING["BOLD"] + "\n3. Do you want to create combined images like the original BeReal memories? (yes/no): " + STYLING["RESET"]).strip().lower()
        if create_combined_images not in ['yes', 'no']:
            logging.error("Invalid input. Please enter 'yes' or 'no'.")

if convert_to_jpeg == 'no' and create_combined_images == 'no':
    print("You chose not to convert images nor do you want to output combined images.\n"
    "The script will therefore only copy images to a new folder and rename them according to your choice without adding metadata or creating new files.\n"
    "Script will continue to run in 5 seconds.")
    #time.sleep(5) # Corrected sleep duration from 10 to 5 as per message

# Function to convert WEBP to JPEG
def convert_webp_to_jpg(image_path):
    if image_path.suffix.lower() == '.webp':
        # Create a .jpg path in the same directory as the source .webp file
        jpg_path = image_path.with_suffix('.jpg')
        try:
            with Image.open(image_path) as img:
                img.convert('RGB').save(jpg_path, "JPEG", quality=80)
                logging.info(f"Converted {image_path} to {jpg_path}.")
            return jpg_path, True
        except Exception as e:
            logging.error(f"Error converting {image_path} to JPEG: {e}")
            return None, False
    else:
        # If it's not a .webp file, return the original path and False for conversion status
        return image_path, False

# Helper function to convert latitude and longitude to EXIF-friendly format
def _convert_to_degrees(value):
    """Convert decimal latitude / longitude to degrees, minutes, seconds (DMS)"""
    d = int(value)
    m = int((value - d) * 60)
    s = (value - d - m/60) * 3600.00

    # Convert to tuples of (numerator, denominator)
    d = (d, 1)
    m = (m, 1)
    s = (int(s * 100), 100)  # Assuming 2 decimal places for seconds for precision

    return (d, m, s)

# Function to update EXIF data
def update_exif(image_path, datetime_original, location=None, caption=None):
    try:
        exif_dict = piexif.load(image_path.as_posix())

        # Ensure the '0th' and 'Exif' directories are initialized
        if '0th' not in exif_dict:
            exif_dict['0th'] = {}
        if 'Exif' not in exif_dict:
            exif_dict['Exif'] = {}

        # Update datetime original
        exif_dict['Exif'][piexif.ExifIFD.DateTimeOriginal] = datetime_original.strftime("%Y:%m:%d %H:%M:%S")
        datetime_print = datetime_original.strftime("%Y:%m:%d %H:%M:%S")
        # logging.info(f"Found datetime: {datetime_print}") # Can be verbose
        # logging.info(f"Added capture date and time.") # Can be verbose

        # Update GPS information if location is provided
        if location and 'latitude' in location and 'longitude' in location:
            # logging.info(f"Found location: {location}") # Can be verbose
            gps_ifd = {
                piexif.GPSIFD.GPSLatitudeRef: 'N' if location['latitude'] >= 0 else 'S',
                piexif.GPSIFD.GPSLatitude: _convert_to_degrees(abs(location['latitude'])),
                piexif.GPSIFD.GPSLongitudeRef: 'E' if location['longitude'] >= 0 else 'W',
                piexif.GPSIFD.GPSLongitude: _convert_to_degrees(abs(location['longitude'])),
            }
            exif_dict['GPS'] = gps_ifd
            # logging.info(f"Added GPS location.") # Can be verbose

        # Transfer caption as title in ImageDescription
        if caption:
            # logging.info(f"Found caption: {caption}") # Can be verbose
            exif_dict['0th'][piexif.ImageIFD.ImageDescription] = caption.encode('utf-8')
            # logging.info(f"Updated title with caption.") # Can be verbose
        
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, image_path.as_posix())
        logging.info(f"Updated EXIF data for {image_path}.")
        
    except Exception as e:
        logging.error(f"Failed to update EXIF data for {image_path}: {e}")

# Function to update IPTC information
def update_iptc(image_path_str, caption): # Expects a string path
    try:
        # Load the IPTC data from the image
        info = IPTCInfo(image_path_str, force=True)  # Use force=True to create IPTC data if it doesn't exist
        
        # Check for errors (known issue with iptcinfo3 creating _markers attribute error)
        if not hasattr(info, '_markers'):
            info._markers = [] # type: ignore
        
        # Update the "Caption-Abstract" field
        if caption:
            info['caption/abstract'] = caption
            # logging.info(f"Caption added to image for IPTC.") # Can be verbose

        # Add static IPTC tags and keywords
        info['source'] = source_app
        info['originating program'] = processing_tool

        # Save the changes back to the image
        info.save_as(image_path_str)
        logging.info(f"Updated IPTC data for {image_path_str}")
    except Exception as e:
        logging.error(f"Failed to update IPTC data for {image_path_str}: {e}")


# Function to handle deduplication
def get_unique_filename(path):
    if not path.exists():
        return path
    else:
        prefix = path.stem
        suffix = path.suffix
        counter = 1
        new_name_path = path
        while new_name_path.exists():
            new_name_path = new_name_path.with_name(f"{prefix}_{counter}{suffix}")
            counter += 1
        return new_name_path

def combine_images_with_resizing(primary_path, secondary_path):
    # Parameters for rounded corners, outline and position
    corner_radius = 60
    outline_size = 7
    position = (55, 55)

    # Load primary and secondary images
    # Ensure paths are strings for Image.open, though Path objects are usually fine
    primary_image = Image.open(str(primary_path))
    secondary_image = Image.open(str(secondary_path))


    # Resize the secondary image using LANCZOS resampling for better quality
    scaling_factor = 1/3.33333333  
    width, height = secondary_image.size
    new_width = int(width * scaling_factor)
    new_height = int(height * scaling_factor)
    resized_secondary_image = secondary_image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # Ensure secondary image has an alpha channel for transparency
    if resized_secondary_image.mode != 'RGBA':
        resized_secondary_image = resized_secondary_image.convert('RGBA')

    # Create mask for rounded corners
    mask = Image.new('L', (new_width, new_height), 0)
    draw_mask = ImageDraw.Draw(mask) # Use a different variable name for the Draw object
    draw_mask.rounded_rectangle((0, 0, new_width, new_height), corner_radius, fill=255)

    # Apply the rounded corners mask to the secondary image
    resized_secondary_image.putalpha(mask)

    # Create a new blank image with the size of the primary image
    combined_image = Image.new("RGB", primary_image.size)
    combined_image.paste(primary_image, (0, 0))    

    # Draw the black outline with rounded corners directly on the combined image
    outline_layer = Image.new('RGBA', combined_image.size, (0, 0, 0, 0))  # Transparent layer for drawing the outline
    draw_outline = ImageDraw.Draw(outline_layer) # Use a different variable name
    outline_box = [position[0] - outline_size, position[1] - outline_size, position[0] + new_width + outline_size, position[1] + new_height + outline_size]
    draw_outline.rounded_rectangle(outline_box, corner_radius + outline_size, fill=(0, 0, 0, 255))

    # Merge the outline layer with the combined image
    combined_image.paste(outline_layer, (0, 0), outline_layer)

    # Paste the secondary image onto the combined image using its alpha channel as the mask
    combined_image.paste(resized_secondary_image, position, resized_secondary_image)
    
    primary_image.close()
    secondary_image.close()
    resized_secondary_image.close()
    mask.close()
    outline_layer.close()

    return combined_image

# Function to clean up backup files left behind by iptcinfo3
def remove_backup_files(directory):
    # List all files in the given directory
    for filename in os.listdir(directory):
        # Check if the filename ends with '~'
        if filename.endswith('~'):
            # Construct the full path to the file
            file_path = os.path.join(directory, filename)
            try:
                # Remove the file
                os.remove(file_path)
                logging.info(f"Removed backup file: {file_path}")
            except Exception as e:
                logging.warning(f"Failed to remove backup file {file_path}: {e}")

# Load the JSON file
try:
    with open('posts.json', encoding="utf8") as f:
        data = json.load(f)
except FileNotFoundError:
    logging.error("JSON file not found. Please check the path.")
    exit()

# Process files
for entry in data:
    try:
        # Extract only the filename from the path and then append it to the photo_folder path
        primary_filename_str = Path(entry['primary']['path']).name
        secondary_filename_str = Path(entry['secondary']['path']).name
        
        primary_path_initial = photo_folder / primary_filename_str
        secondary_path_initial = photo_folder / secondary_filename_str

        if not os.path.exists(primary_path_initial):
            primary_path_initial = bereal_folder / primary_filename_str
        if not os.path.exists(secondary_path_initial): # Check secondary path separately
            secondary_path_initial = bereal_folder / secondary_filename_str
        
        # Check if files exist after attempting both folders
        if not primary_path_initial.exists():
            logging.error(f"Primary image not found: {primary_filename_str} in {photo_folder} or {bereal_folder}")
            skipped_files_count +=1 # Count as skipped if primary is missing
            if not secondary_path_initial.exists(): # If secondary also missing
                 skipped_files_count +=1 # Count as skipped
            continue # Skip this entry if primary is missing

        if not secondary_path_initial.exists():
            logging.error(f"Secondary image not found: {secondary_filename_str} in {photo_folder} or {bereal_folder}")
            skipped_files_count +=1 # Count as skipped if secondary is missing
            # We might still process primary if it exists, or skip. Current logic processes pair.
            # For now, assume we need both to proceed with an "entry"
            continue


        taken_at = datetime.strptime(entry['takenAt'], "%Y-%m-%dT%H:%M:%S.%fZ")
        location = entry.get('location')  # This will be None if 'location' is not present
        caption = entry.get('caption')  # This will be None if 'caption' is not present

        
        for path_current, role in [(primary_path_initial, 'primary'), (secondary_path_initial, 'secondary')]:
            logging.info(f"Processing {role} image: {path_current}")
            
            # Determine the path that will be processed (original or converted)
            path_to_process = path_current
            converted_in_this_step = False

            if convert_to_jpeg == 'yes':
                if path_current.suffix.lower() == '.webp':
                    converted_temp_path, converted_in_this_step = convert_webp_to_jpg(path_current)
                    if converted_temp_path is None: # Conversion failed
                        skipped_files_count += 1
                        logging.error(f"Skipping {path_current} due to conversion error.")
                        # Use continue to skip processing for this specific file (primary or secondary)
                        # This requires restructuring how primary_images/secondary_images are paired.
                        # For simplicity, if one file in a pair fails conversion, we might need to skip the pair for combining.
                        # Let's assume for now we mark it and it won't be added to lists for combining if it fails.
                        # This part of the loop might need a flag to signal to skip adding to primary_images/secondary_images.
                        if role == 'primary': primary_images.append(None) # Placeholder for failed primary
                        else: secondary_images.append(None) # Placeholder for failed secondary
                        continue # Skip this specific file (primary or secondary)
                    path_to_process = converted_temp_path # Now points to the .jpg file in the original folder
                    if converted_in_this_step:
                        converted_files_count += 1
                # If already .jpg, path_to_process remains path_current, converted_in_this_step is False
            
            # Adjust filename based on user's choice
            time_str = taken_at.strftime("%Y-%m-%dT%H-%M-%S")
            original_filename_stem = Path(path_current).stem
            
            if convert_to_jpeg == 'yes': # Output will be JPEG
                new_extension = '.jpg'
                if keep_original_filename == 'yes':
                    # If converted from webp, path_to_process.name is already .jpg. If original was .jpg, also .jpg
                    new_filename_base = f"{time_str}_{role}_{path_to_process.stem}" 
                else:
                    new_filename_base = f"{time_str}_{role}"
            else: # Output will be WebP (or original format if not WebP)
                new_extension = path_to_process.suffix # Keep original extension if not converting to JPEG
                if keep_original_filename == 'yes':
                    new_filename_base = f"{time_str}_{role}_{original_filename_stem}"
                else:
                    new_filename_base = f"{time_str}_{role}"
            
            new_final_filename = f"{new_filename_base}{new_extension}"
            new_final_path = output_folder / new_final_filename
            new_final_path = get_unique_filename(new_final_path)

            # Move/Copy the file to its final destination
            if path_to_process.exists():
                if converted_in_this_step: # If it was converted, path_to_process is temporary, so move it
                    shutil.move(str(path_to_process), new_final_path)
                else: # If not converted (original WebP and no JPEG conversion, or already JPEG), copy it
                    shutil.copy2(str(path_current), new_final_path)
            else:
                logging.error(f"Source path {path_to_process} does not exist before moving/copying. Skipping file.")
                if role == 'primary': primary_images.append(None) 
                else: secondary_images.append(None)
                skipped_files_count +=1
                continue


            # Add metadata if converted to JPEG or if it was already JPEG and conversion was 'yes' (implicit)
            if new_final_path.suffix.lower() == '.jpg': # Only add metadata to JPEGs
                update_exif(new_final_path, taken_at, location, caption)
                update_iptc(str(new_final_path), caption)

                # === FIX: Re-open and save the JPEG with Pillow to ensure integrity ===
                try:
                    with Image.open(new_final_path) as img_to_resave:
                        current_exif = img_to_resave.info.get('exif')
                        img_to_resave.save(new_final_path, "JPEG", quality=80, exif=current_exif, icc_profile=img_to_resave.info.get('icc_profile'))
                    logging.info(f"Re-saved {new_final_path} with Pillow to ensure integrity after metadata updates.")
                except Exception as e: # Corrected syntax here
                    logging.error(f"Failed to re-open and re-save {new_final_path}: {e}. File might be corrupted.")
                    if role == 'primary': primary_images.append(None) 
                    else: secondary_images.append(None)
                    skipped_files_count +=1
                    continue # Skip adding this problematic file to lists for combining
                # === End of FIX ===

            if role == 'primary':
                primary_images.append({
                    'path': new_final_path,
                    'taken_at': taken_at,
                    'location': location,
                    'caption': caption
                })
            else:
                secondary_images.append(new_final_path)

            logging.info(f"Successfully processed {role} image to {new_final_path}")
            processed_files_count += 1
            print("") # Newline for readability
    except Exception as e:
        logging.error(f"Error processing entry {entry}: {e}")
        # Increment skipped count for both potential files in the entry if a general error occurs
        skipped_files_count += 2 


# Create combined images if user chose 'yes'
if create_combined_images == 'yes':
    output_folder_combined.mkdir(parents=True, exist_ok=True)

    valid_primary_images = [p for p in primary_images if p is not None]
    valid_secondary_images = [s for s in secondary_images if s is not None]
    
    # Ensure we have pairs
    num_pairs = min(len(valid_primary_images), len(valid_secondary_images))

    for i in range(num_pairs):
        primary_data = valid_primary_images[i]
        secondary_image_path_for_combine = valid_secondary_images[i]

        if primary_data is None or secondary_image_path_for_combine is None:
            logging.warning("Skipping combined image creation due to a missing primary or secondary image in a pair.")
            continue

        primary_image_path_for_combine = primary_data['path']
        primary_taken_at = primary_data['taken_at']
        primary_location = primary_data['location']
        primary_caption = primary_data['caption']

        # Ensure paths exist before trying to combine
        if not primary_image_path_for_combine.exists() or not secondary_image_path_for_combine.exists():
            logging.error(f"Cannot combine: one or both files missing. Primary: {primary_image_path_for_combine}, Secondary: {secondary_image_path_for_combine}")
            continue

        timestamp_str = primary_image_path_for_combine.stem.split('_')[0] # Assumes YYYY-MM-DDTHH-MM-SS format at start

        # Corrected: Save combined image as JPEG with .jpg extension
        combined_filename = f"{timestamp_str}_combined.jpg"
        combined_image_final_path = output_folder_combined / combined_filename
        combined_image_final_path = get_unique_filename(combined_image_final_path) # Ensure unique name

        try:
            combined_image_pil = combine_images_with_resizing(primary_image_path_for_combine, secondary_image_path_for_combine)
            combined_image_pil.save(combined_image_final_path, 'JPEG', quality=80) # Save as JPEG
            combined_image_pil.close()
            combined_files_count += 1
            logging.info(f"Combined image saved: {combined_image_final_path}")

            # Add metadata to the new combined JPEG
            update_exif(combined_image_final_path, primary_taken_at, primary_location, primary_caption)
            update_iptc(str(combined_image_final_path), primary_caption)

            # === FIX: Re-save the combined JPEG with Pillow to ensure integrity ===
            try:
                with Image.open(combined_image_final_path) as img_to_resave_combined:
                    current_exif_combined = img_to_resave_combined.info.get('exif')
                    img_to_resave_combined.save(combined_image_final_path, "JPEG", quality=80, exif=current_exif_combined, icc_profile=img_to_resave_combined.info.get('icc_profile'))
                logging.info(f"Re-saved combined image {combined_image_final_path} with Pillow to ensure integrity.")
            except Exception as e_resave_combined:
                logging.error(f"Failed to re-open and re-save combined image {combined_image_final_path}: {e_resave_combined}.")
            # === End of FIX ===

        except FileNotFoundError as e_fnf:
            logging.error(f"Error creating combined image. File not found: {e_fnf}")
        except UnidentifiedImageError as e_uie:
             logging.error(f"Error creating combined image. UnidentifiedImageError for one of the inputs: {e_uie}. Primary: {primary_image_path_for_combine}, Secondary: {secondary_image_path_for_combine}")
        except Exception as e_combine:
            logging.error(f"Error during combined image creation or metadata update for {combined_image_final_path}: {e_combine}")
        
        print("") # Newline for readability

# Clean up backup files
print(STYLING['BOLD'] + "\nRemoving backup files left behind by iptcinfo3..." + STYLING["RESET"])
remove_backup_files(output_folder)
if create_combined_images == 'yes': remove_backup_files(output_folder_combined)
print("Backup file cleanup finished.\n")

# Summary
# Recalculate number_of_files if bereal_folder was used
total_input_files = count_files_in_folder(photo_folder)
if os.path.exists(bereal_folder):
    total_input_files += count_files_in_folder(bereal_folder)


logging.info(f"Finished processing.\n"
             f"Total input WebP-files found: {total_input_files}\n"
             f"Total files processed (primary/secondary instances): {processed_files_count}\n"
             f"Files converted WebP to JPEG: {converted_files_count}\n"
             f"Combined images created: {combined_files_count}\n"
             f"Files/operations skipped due to errors: {skipped_files_count}")
