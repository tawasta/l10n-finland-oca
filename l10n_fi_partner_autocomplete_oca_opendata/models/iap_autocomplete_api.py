import requests

from odoo import api, models
from odoo.exceptions import ValidationError


class IapAutocompleteApi(models.AbstractModel):
    _inherit = "iap.autocomplete.api"

    @api.model
    def _contact_iap(self, local_endpoint, action, params, timeout=15):
        account = self.env["iap.account"].get("partner_autocomplete")

        if account.provider == "prh":
            if action == "search_by_name":
                query = params.get("query")
                if query and len(query) == 9 and query[7] == "-":
                    # If query looks like a business id, search by business id
                    # Business ID is something like "1234567-1"
                    params["businessId"] = query
                else:
                    # Otherwise, search by name
                    params["name"] = query
            elif action == "enrich_by_duns":
                # This is the action to enrich company details.
                # We are misusing it a bit
                params["businessId"] = params.get("duns")

            base_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/"
            endpoint = "companies"
            api_url = f"{base_url}{endpoint}"
            response = requests.get(api_url, params=params, timeout=10)

            companies = self._parse_prh_response(
                response, create_industry=account.prh_use_industry
            )

            if action == "enrich_by_duns":
                # Only return the first finding
                companies = companies[0] if companies else {}

            res = {"data": companies}
        else:
            res = super()._contact_iap(local_endpoint, action, params, timeout=timeout)

        return res

    def _parse_prh_response(self, response, create_industry=False):
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            raise ValidationError(self.env._("PRH API request failed: %s", e)) from e

        companies = response.json().get("companies", [])

        company_list = []

        for company in companies:
            values = self._prh_parse_company(company, create_industry=create_industry)

            company_list.append(values)

        return company_list

    def _prh_parse_company(self, company, create_industry=True):
        values = {}
        # TODO: can we get the country from response?
        country_code = "FI"
        values["country_code"] = country_code
        values["preferred_language"] = "fi_FI"

        if company.get("names"):
            # Use the first found name
            # TODO: better matching with date awarness
            values["name"] = company.get("names")[0].get("name")

        if company.get("businessId"):
            business_id = company.get("businessId").get("value")
            values["company_registry"] = business_id
            values["vat"] = f"{country_code}{business_id.replace('-', '')}"
            # We are misusing this field a bit here
            values["duns"] = business_id

        if company.get("website"):
            values["website"] = company["website"].get("url")

        # Update address details
        if company.get("addresses"):
            # TODO: this can only handle the first address.
            #  We could create affiliate companies from other addresses

            address = company["addresses"][0]
            street = []

            if address.get("street"):
                street.append(address["street"])
            if address.get("postCode"):
                values["zip"] = address["postCode"]
            if address.get("postOffices"):
                values["city"] = address["postOffices"][0].get("city")
            if address.get("buildingNumber"):
                street.append(address["buildingNumber"])
            if address.get("entrance"):
                street.append(address["entrance"])
            if address.get("apartmentNumber"):
                street.append(address["apartmentNumber"])
            if address.get("apartmentIdSuffix"):
                street.append(address["apartmentIdSuffix"])
            if address.get("co"):
                street.append(address["co"])

            if street:
                # Construct the street
                values["street"] = " ".join(street)

            business_line = company.get("mainBusinessLine")
            if create_industry and business_line:
                # Not working yet
                pass
                # values["industry_id"] = \
                # self._get_or_create_industry(business_line).id

        return values

    def _get_or_create_industry(self, business_line):
        # Get or create an industry

        language_code = str(
            self.env["ir.config_parameter"].sudo().get_param("prh.language_code")
        )
        name = ""

        for desc in business_line.get("descriptions"):
            if desc.get("languageCode") == language_code:
                name = desc.get("description")

        code = business_line.get("type")

        industry_model = self.env["res.partner.industry"].sudo()

        industry = industry_model.search(
            ["|", ("name", "=ilike", name), ("full_name", "ilike", code)], limit=1
        )

        if not industry:
            industry = industry_model.create(
                {
                    "name": name,
                    "full_name": f"[{code}] {name}",
                }
            )

        return industry
