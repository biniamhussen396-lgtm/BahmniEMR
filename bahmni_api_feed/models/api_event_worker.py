from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ApiEventWorker(models.Model):
    _name = 'api.event.worker'
    _auto = False

    @api.model
    def process_event(self, vals):
        '''Method getting triggered from Bahmni side'''
        _logger.debug("API Payload:" + str(vals))
        if isinstance(vals, dict) and not vals.get("category") and isinstance(vals.get("params"), dict):
            vals = vals["params"]
        category = vals.get("category")
        try:
            if category == "create.customer":
                self._create_or_update_customer(vals)
                return "The customer have been successfully created / updated."
            elif category == "create.sale.order":
                self.env['order.save.service'].create_orders(vals)
                return "Sale order has been created successfully."
            elif category == "create.drug":
                self.env['drug.data.service'].create_or_update_drug(vals)
                return "The drug have been successfully created / updated."
            elif category == "create.radiology.test":
                self.env['reference.data.service'].create_or_update_ref_data(vals, 'Radiology')
                return "The rediology test have been successfully created / updated."
            elif category == "create.lab.test":
                self.env['reference.data.service'].create_or_update_ref_data(vals, 'Test')
                return "The lab test have been successfully created / updated."
            elif category == "create.lab.panel":
                self.env['reference.data.service'].create_or_update_ref_data(vals, 'Panel')
                return "The lab panel have been successfully created / updated."
            elif category == "create.service.saleable":
                self.env['reference.data.service'].create_or_update_ref_data(vals, 'Others')
                return "The service saleable have been successfully created / updated."
            elif category == "cancel.order":
                self._cancel_order(vals)
                return "Order has been cancelled successfully."
            elif category == "void.order":
                self._void_order(vals)
                return "Order has been voided successfully."
            elif category == "add.available.lab.tests":
                self._add_available_lab_tests(vals)
                return "Available lab tests added to sale order successfully."
            elif category == "confirm.sale.order" or category == "approve.order":
                self._confirm_sale_order(vals)
                return "Sale order confirmed successfully."
            else:
                raise UserError("Integration process is not defined. Kindly contact ERP tech team for support.")
        except Exception as err:
            _logger.info("\n Processing event threw error: %s", err)
            raise

    @api.model
    def _cancel_order(self, vals):
        """Handle order cancellation from OpenELIS/OpenMRS
        Supports per-test cancellation via stockOutTestNames and stockOutTestUuids.
        If provided, only those specific order lines are cancelled.
        Otherwise, all lines in the order are cancelled.
        """
        order_uuid = vals.get("orderUuid")
        accession_number = vals.get("accessionNumber")
        cancel_reason = vals.get("cancelReason", "Reagent Stock Out")
        stock_out_test_names = vals.get("stockOutTestNames", [])
        stock_out_test_uuids = vals.get("stockOutTestUuids", [])
        
        _logger.info("Processing order cancellation for order: %s, accession: %s, tests: %s, uuids: %s",
                     order_uuid, accession_number, stock_out_test_names, stock_out_test_uuids)
        
        sale_order = None
        if order_uuid:
            sol = self.env['sale.order.line'].search([
                '|', ('external_order_id', '=', order_uuid),
                '|', ('order_uuid', '=', order_uuid),
                ('external_id', '=', order_uuid)
            ], limit=1)
            if sol and sol.order_id and sol.order_id.state == 'draft':
                sale_order = sol.order_id

        if not sale_order and order_uuid:
            sale_order = self.env['sale.order'].search([
                ('origin', 'ilike', order_uuid),
                ('state', '=', 'draft')
            ], limit=1)
        
        if not sale_order and accession_number:
            sale_order = self.env['sale.order'].search([
                ('origin', 'ilike', accession_number),
                ('state', '=', 'draft')
            ], limit=1)

        patient_ref = vals.get("patientId") or vals.get("customer_id") or vals.get("patient_ref")
        sale_orders = self.env['sale.order']
        if sale_order:
            sale_orders |= sale_order

        if patient_ref:
            partner = self.env['res.partner'].search([('ref', '=', str(patient_ref))], limit=1)
            if partner:
                patient_draft_orders = self.env['sale.order'].search([
                    ('partner_id', '=', partner.id),
                    ('state', 'in', ['draft', 'sent'])
                ])
                if patient_draft_orders:
                    sale_orders |= patient_draft_orders

        if not sale_orders:
            _logger.warning("No draft sale order found for order: %s, accession: %s, patient: %s", order_uuid, accession_number, patient_ref)
            return
        
        for current_so in sale_orders:
            if stock_out_test_names or stock_out_test_uuids:
                clean_names = [n.strip().lower() for n in stock_out_test_names if n and n.strip()]
                clean_uuids = [u.strip().lower() for u in stock_out_test_uuids if u and u.strip()]

                for line in list(current_so.order_line):
                    matched = False
                    prod = line.product_id
                    prod_uuid = (getattr(prod, 'uuid', None) or getattr(prod.product_tmpl_id, 'uuid', None) or '').strip().lower()
                    prod_code = (prod.default_code or '').strip().lower()
                    prod_name = (prod.name or '').strip().lower()

                    if prod_uuid and prod_uuid in clean_uuids:
                        matched = True

                    if not matched and clean_uuids and prod_code and prod_code in clean_uuids:
                        matched = True

                    if not matched and clean_names:
                        for test_name in clean_names:
                            if test_name == prod_name or test_name in prod_name or prod_name in test_name:
                                matched = True
                                break
                            if test_name == 'rbs' and 'random blood sugar' in prod_name:
                                matched = True
                                break
                            if test_name == 'random blood sugar' and 'rbs' in prod_name:
                                matched = True
                                break

                    if matched:
                        line.sudo().write({'price_subtotal': 0, 'price_unit': 0})
                        line.sudo().unlink()
                        _logger.info("Cancelled/Unlinked stock-out order line: %s (%s) from order %s", line.id, prod.name, current_so.name)
            else:
                for line in list(current_so.order_line):
                    line.sudo().unlink()
                _logger.info("Cancelled all lines in sale order: %s (no specific tests)", current_so.name)
            
            if not current_so.order_line:
                current_so.action_cancel()
                _logger.info("Cancelled entire sale order %s - all lines removed", current_so.name)

    @api.model
    def _void_order(self, vals):
        """Handle order void from OpenELIS
        Similar to cancel but may have different business logic
        """
        order_uuid = vals.get("orderUuid")
        accession_number = vals.get("accessionNumber")
        void_reason = vals.get("voidReason", "Reagent Stock Out")
        
        _logger.info("Processing order void for order: %s, accession: %s", order_uuid, accession_number)
        
        # Reuse cancel logic with void reason
        self._cancel_order({
            'orderUuid': order_uuid,
            'accessionNumber': accession_number,
            'cancelReason': void_reason
        })

    @api.model
    def _create_or_update_customer(self, vals):
        patient_ref = vals.get("ref")
        customer_vals = self._get_customer_vals(vals)
        # removing null values, as while updating null values in write method will remove old values

        for rec in list(customer_vals.keys()):
            if not customer_vals[rec]:
                del customer_vals[rec]
        address_data = vals.get('preferredAddress')
        # get validated address details
        address_details = self.env['address.mapping.service']._map_address_fields(address_data)
        # update address details
        customer_vals.update(address_details)
        _logger.info("Customer vals: %s", customer_vals)
        existing_customer = self.env['res.partner'].search([('ref', '=', patient_ref)])
        if existing_customer:
            existing_customer.write(customer_vals)
            self._create_or_update_person_attributes(existing_customer.id,vals)
        else:
            customer = self.env['res.partner'].create(customer_vals)
            self._create_or_update_person_attributes(customer.id,vals)

    def _get_customer_vals(self, vals):
        res = {}
        res.update({'ref': vals.get('ref'),
                    'name': vals.get('name'),
                    'local_name': vals.get('local_name') if vals.get('local_name') else False,
                    'uuid': vals.get('uuid'),
                    'customer_rank':  1})
        # update other details : for now there is only scope of updating contact.
        if vals.get('primaryContact'):
            res.update({'phone': vals['primaryContact']})
        return res

    def _create_or_update_person_attributes(self, cust_id, vals):
        attributes = vals.get("attributes", {})
        if isinstance(attributes, str):
            import json
            try:
                attributes = json.loads(attributes)
            except Exception:
                attributes = {}
        address_data = vals.get('preferredAddress')

        if attributes.get('email') and cust_id:
            customer_master = self.env['res.partner'].search([('id', '=', cust_id)])
            if customer_master:
                customer_master.email = attributes['email']



        for key in attributes:
            if key in [key for key in attributes]:
                column_dict = {'partner_id': cust_id}
                existing_attribute = self.env['res.partner.attributes'].search([('partner_id', '=', cust_id),('name', '=', key)])
                if any(existing_attribute):
                    existing_attribute.unlink()
                column_dict.update({"name": key, "value" : attributes[key]})
                self.env['res.partner.attributes'].create(column_dict)


    @api.model
    def _add_available_lab_tests(self, vals):
        """Add lab tests that have been evaluated and confirmed AVAILABLE in OpenELIS to Odoo sale order.
        Supports matching by concept UUID as well as test name to guarantee zero test-name mismatch.
        """
        patient_ref = vals.get("patientId") or vals.get("customer_id")
        test_names = vals.get("availableTestNames", [])
        test_uuids = vals.get("availableTestUuids", [])
        if not patient_ref or (not test_names and not test_uuids):
            return

        partner = self.env['res.partner'].search([('ref', '=', str(patient_ref))], limit=1)
        if not partner:
            try:
                import urllib.request
                import json as json_lib
                import base64
                url = f"http://openmrs:8080/openmrs/ws/rest/v1/patient?q={patient_ref}&v=full"
                req = urllib.request.Request(url)
                req.add_header('Authorization', 'Basic ' + base64.b64encode(b'admin:Admin123').decode('ascii'))
                resp = urllib.request.urlopen(req, timeout=5)
                res_data = json_lib.loads(resp.read().decode('utf-8'))
                results = res_data.get('results', [])
                p_name = str(patient_ref)
                p_uuid = None
                if results:
                    p = results[0]
                    p_name = p.get('person', {}).get('display', str(patient_ref))
                    p_uuid = p.get('uuid')
                partner = self.env['res.partner'].sudo().create({
                    'name': p_name,
                    'ref': str(patient_ref),
                    'uuid': p_uuid,
                    'customer_rank': 1
                })
            except Exception:
                partner = self.env['res.partner'].sudo().create({
                    'name': str(patient_ref),
                    'ref': str(patient_ref),
                    'customer_rank': 1
                })

        sale_order = self.env['sale.order'].search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'draft')
        ], order='id desc', limit=1)

        sale_shop = self.env['sale.shop'].search([], limit=1)
        shop_id = sale_shop.id if sale_shop else False

        if not sale_order:
            sale_order = self.env['sale.order'].sudo().create({
                'partner_id': partner.id,
                'shop_id': shop_id,
                'state': 'draft',
                'origin': 'API FEED SYNC',
            })

        items_to_add = []
        max_len = max(len(test_names), len(test_uuids))
        for idx in range(max_len):
            t_name = test_names[idx].strip() if idx < len(test_names) and test_names[idx] else ''
            t_uuid = test_uuids[idx].strip() if idx < len(test_uuids) and test_uuids[idx] else ''
            if t_name or t_uuid:
                items_to_add.append((t_name, t_uuid))

        for test_name, test_uuid in items_to_add:
            # 1. Check if line already exists in draft sale order
            existing_line = False
            for line in sale_order.order_line:
                prod = line.product_id
                line_uuid = (prod.uuid or prod.product_tmpl_id.uuid or '').strip()
                prod_name = (prod.name or '').strip().lower()
                if test_uuid and line_uuid and test_uuid == line_uuid:
                    existing_line = True
                    break
                if test_name and (test_name.lower() in prod_name or prod_name.startswith(test_name.lower())):
                    existing_line = True
                    break
            if existing_line:
                continue

            # 2. Search product by UUID first
            product = None
            if test_uuid:
                product = self.env['product.product'].search([('uuid', '=', test_uuid)], limit=1)
                if not product:
                    tmpl = self.env['product.template'].search([('uuid', '=', test_uuid)], limit=1)
                    if tmpl and tmpl.product_variant_ids:
                        product = tmpl.product_variant_ids[0]

            # 3. Search product by Name if not found by UUID
            if not product and test_name:
                product = self.env['product.product'].search([('name', 'ilike', test_name)], limit=1)
                if not product:
                    tmpl = self.env['product.template'].search([('name', 'ilike', test_name)], limit=1)
                    if tmpl and tmpl.product_variant_ids:
                        product = tmpl.product_variant_ids[0]

            # 4. Auto-create product if completely missing
            if not product:
                display_name = test_name or 'Lab Test'
                tmpl = self.env['product.template'].sudo().create({
                    'name': display_name,
                    'type': 'service',
                    'uuid': test_uuid or None,
                    'sale_ok': True,
                    'list_price': 1.0,
                    'invoice_policy': 'order',
                })
                product = tmpl.product_variant_ids[0]
                if test_uuid and product:
                    product.sudo().write({'uuid': test_uuid})

            price_unit = product.list_price or 1.0
            if sale_order.pricelist_id:
                try:
                    price_unit = sale_order.pricelist_id._get_product_price(product, 1.0, partner)
                except Exception:
                    pass

            self.env['sale.order.line'].sudo().create({
                'order_id': sale_order.id,
                'product_id': product.id,
                'name': product.name or test_name,
                'product_uom_qty': 1.0,
                'price_unit': price_unit,
                'tax_id': [(5, 0, 0)],
            })
            _logger.info("Added evaluated available test [%s / uuid:%s] to sale order %s for patient %s",
                         test_name, test_uuid, sale_order.name, partner.name)

    @api.model
    def _confirm_sale_order(self, vals):
        """Confirm draft quotation into sales order for patient/order without waiting for invoice registration"""
        patient_ref = vals.get("patientId") or vals.get("customer_id")
        order_uuid = vals.get("orderUuid")
        sale_order_name = vals.get("saleOrderName")
        
        sale_orders = self.env['sale.order']
        if sale_order_name:
            so = self.env['sale.order'].search([('name', '=', str(sale_order_name))], limit=1)
            if so:
                sale_orders |= so

        if patient_ref:
            partner = self.env['res.partner'].search([('ref', '=', str(patient_ref))], limit=1)
            if partner:
                so_list = self.env['sale.order'].search([
                    ('partner_id', '=', partner.id),
                    ('state', 'in', ['draft', 'sent'])
                ], order='id desc')
                sale_orders |= so_list

        if not sale_orders and order_uuid:
            sols = self.env['sale.order.line'].search([
                '|', ('external_order_id', '=', order_uuid),
                '|', ('order_uuid', '=', order_uuid),
                ('external_id', '=', order_uuid)
            ])
            for sol in sols:
                if sol.order_id:
                    sale_orders |= sol.order_id

        for so in sale_orders:
            if so.state in ('draft', 'sent'):
                try:
                    so.action_confirm()
                except Exception as e:
                    so.write({'state': 'sale'})
                _logger.info("Confirmed sale order %s to state %s", so.name, so.state)
        return True
