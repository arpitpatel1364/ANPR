"""
PDF Export functionality for detection records with images
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from datetime import datetime
import os
import tempfile
from PIL import Image as PILImage


def create_pdf_export(detections, output_path, include_images=True):
    """
    Create a PDF export of detection records with images
    
    Args:
        detections: List of detection dictionaries
        output_path: Path to save the PDF file
        include_images: Whether to include images in the PDF
    """
    doc = SimpleDocTemplate(output_path, pagesize=letter,
                          rightMargin=72, leftMargin=72,
                          topMargin=72, bottomMargin=18)
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a472a'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2d5016'),
        spaceAfter=6
    )
    
    normal_style = styles['Normal']
    normal_style.fontSize = 10
    
    # Title (more compact)
    title = Paragraph("ANPR Detection Records Export", title_style)
    elements.append(title)
    elements.append(Spacer(1, 0.1*inch))
    
    # Export info (more compact)
    export_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    info_text = f"<b>Export Date:</b> {export_date} | <b>Total Records:</b> {len(detections)}"
    info_para = Paragraph(info_text, normal_style)
    elements.append(info_para)
    elements.append(Spacer(1, 0.15*inch))
    
    # Process each detection
    for idx, detection in enumerate(detections, 1):
        # Detection header - Use license plate as heading
        license_plate = detection.get('License_Plate', f'Detection #{idx}')
        status = detection.get('Verification_Status', 'N/A')
        status_color = colors.HexColor('#2d5016') if status == 'VERIFIED' else colors.HexColor('#d32f2f')
        
        header_text = f"<b>{license_plate}</b> <font color='{status_color.hexval()}' size='12'>({status})</font>"
        header = Paragraph(header_text, heading_style)
        elements.append(header)
        elements.append(Spacer(1, 0.05*inch))
        
        # Compact detection details table - 2 columns, 3 rows
        details_data = [
            ['Timestamp:', detection.get('Timestamp', 'N/A'), 'Camera:', detection.get('Camera_Source', 'N/A')],
            ['Confidence:', f"{float(detection.get('Detection_Confidence', 0))*100:.1f}%", 'Processing Time:', f"{detection.get('Processing_Time_MS', '0')} ms"],
        ]
        
        details_table = Table(details_data, colWidths=[1.2*inch, 2.3*inch, 1.2*inch, 2.3*inch])
        details_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#e8f5e9')),
            ('BACKGROUND', (2, 0), (2, -1), colors.HexColor('#e8f5e9')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTNAME', (3, 0), (3, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(details_table)
        elements.append(Spacer(1, 0.1*inch))
        
        # Images section - side by side layout
        if include_images:
            image_cells = []
            captions = []
            
            # Full Annotated Image
            if detection.get('Image_Full_Annotated'):
                img_path = _get_image_path(detection['Image_Full_Annotated'])
                if img_path and os.path.exists(img_path):
                    try:
                        img_obj = _get_image_object(img_path, max_width=3*inch, max_height=2*inch)
                        if img_obj:
                            image_cells.append(img_obj)
                            captions.append("Full Annotated Frame")
                    except Exception as e:
                        print(f"Error adding annotated image: {e}")
            
            # Plate Crop Image
            if detection.get('Image_Plate_Crop'):
                img_path = _get_image_path(detection['Image_Plate_Crop'])
                if img_path and os.path.exists(img_path):
                    try:
                        img_obj = _get_image_object(img_path, max_width=3*inch, max_height=2*inch)
                        if img_obj:
                            image_cells.append(img_obj)
                            captions.append("Plate Crop")
                    except Exception as e:
                        print(f"Error adding crop image: {e}")
            
            # Full Raw Image (if annotated not available)
            if not image_cells and detection.get('Image_Full_Raw'):
                img_path = _get_image_path(detection['Image_Full_Raw'])
                if img_path and os.path.exists(img_path):
                    try:
                        img_obj = _get_image_object(img_path, max_width=3*inch, max_height=2*inch)
                        if img_obj:
                            image_cells.append(img_obj)
                            captions.append("Full Raw Frame")
                    except Exception as e:
                        print(f"Error adding raw image: {e}")
            
            # Create side-by-side image table if we have images
            if image_cells:
                # Create table with images side by side
                image_table_data = []
                caption_table_data = []
                
                # Add images to first row
                image_row = []
                for img in image_cells:
                    image_row.append(img)
                # Pad with empty cells if needed to fill 2 columns
                while len(image_row) < 2:
                    image_row.append(Spacer(1, 0.1*inch))
                image_table_data.append(image_row)
                
                # Add captions to second row
                caption_row = []
                for caption_text in captions:
                    caption_style = ParagraphStyle(
                        'Caption',
                        parent=getSampleStyleSheet()['Normal'],
                        fontSize=8,
                        textColor=colors.grey,
                        alignment=TA_CENTER
                    )
                    caption_para = Paragraph(f"<i>{caption_text}</i>", caption_style)
                    caption_row.append(caption_para)
                # Pad with empty cells if needed
                while len(caption_row) < 2:
                    caption_row.append(Spacer(1, 0.1*inch))
                caption_table_data.append(caption_row)
                
                # Create image table
                img_table = Table(image_table_data, colWidths=[3.5*inch, 3.5*inch])
                img_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ]))
                elements.append(img_table)
                
                # Create caption table
                caption_table = Table(caption_table_data, colWidths=[3.5*inch, 3.5*inch])
                caption_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                ]))
                elements.append(caption_table)
                elements.append(Spacer(1, 0.1*inch))
        
        # Add small spacer between detections (no page break - let it flow naturally)
        if idx < len(detections):
            elements.append(Spacer(1, 0.15*inch))
            # Only add page break if we're getting close to page end
            # (This is handled automatically by reportlab, but we can add manual breaks if needed)
    
    # Build PDF
    doc.build(elements)
    return output_path


def _get_image_path(image_url):
    """
    Convert image URL to file system path
    
    Args:
        image_url: Image URL from database (e.g., /static/images/detections/...)
    
    Returns:
        Full file system path to the image
    """
    if not image_url:
        return None
    
    # Remove leading slash if present
    if image_url.startswith('/'):
        image_url = image_url[1:]
    
    # Try different possible base paths
    base_paths = [
        'admin_panel',  # If running from project root
        '',  # If running from admin_panel directory
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Absolute path
    ]
    
    for base in base_paths:
        full_path = os.path.join(base, image_url) if base else image_url
        if os.path.exists(full_path):
            return full_path
    
    # If not found, return None
    return None


def _get_image_object(image_path, max_width=3*inch, max_height=2*inch):
    """
    Get an Image object for use in tables (without caption)
    
    Args:
        image_path: Path to the image file
        max_width: Maximum width for the image
        max_height: Maximum height for the image
    
    Returns:
        Image object or None
    """
    try:
        if PILImage is None:
            # Fallback: use reportlab's Image
            return Image(image_path, width=max_width, height=max_height)
        
        pil_img = PILImage.open(image_path)
        img_width, img_height = pil_img.size
        
        # Calculate size to fit
        if img_width > max_width or img_height > max_height:
            ratio = min(max_width / img_width, max_height / img_height)
            new_width = img_width * ratio
            new_height = img_height * ratio
        else:
            new_width = img_width
            new_height = img_height
        
        return Image(image_path, width=new_width, height=new_height)
        
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")
        return None

def _add_image_to_pdf(image_path, caption):
    """
    Add an image to PDF with caption
    
    Args:
        image_path: Path to the image file
        caption: Caption text for the image
    
    Returns:
        List of flowables (image + caption)
    """
    flowables = []
    
    try:
        # Open and resize image if needed
        if PILImage is None:
            # Fallback: use reportlab's Image which will handle sizing (more compact)
            img = Image(image_path, width=4.5*inch, height=2.5*inch)
            flowables.append(img)
            flowables.append(Spacer(1, 0.05*inch))
        else:
            pil_img = PILImage.open(image_path)
            img_width, img_height = pil_img.size
            
            # Calculate size to fit in PDF (more compact - max width 4.5 inches, maintain aspect ratio)
            max_width = 4.5 * inch
            max_height = 2.5 * inch
            
            if img_width > max_width or img_height > max_height:
                ratio = min(max_width / img_width, max_height / img_height)
                new_width = img_width * ratio
                new_height = img_height * ratio
            else:
                new_width = img_width
                new_height = img_height
            
            # Create reportlab Image
            img = Image(image_path, width=new_width, height=new_height)
            flowables.append(img)
            flowables.append(Spacer(1, 0.05*inch))
        
        # Add caption (more compact)
        caption_style = ParagraphStyle(
            'Caption',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=8,
            textColor=colors.grey,
            alignment=TA_CENTER,
            spaceAfter=0.1*inch
        )
        caption_para = Paragraph(f"<i>{caption}</i>", caption_style)
        flowables.append(caption_para)
        
    except Exception as e:
        print(f"Error processing image {image_path}: {e}")
        # Add error message instead
        error_style = ParagraphStyle(
            'Error',
            parent=getSampleStyleSheet()['Normal'],
            fontSize=9,
            textColor=colors.red,
            alignment=TA_CENTER
        )
        error_para = Paragraph(f"<i>Error loading image: {caption}</i>", error_style)
        flowables.append(error_para)
    
    return flowables

